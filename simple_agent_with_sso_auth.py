"""
Simple Snowflake Query Agent with SSO Authentication
Uses browser-based SSO authentication instead of OAuth tokens
"""

import snowflake.connector
import json
import pandas as pd
import sys
import os
import re
from datetime import datetime

try:
    import msal
except ImportError:
    msal = None

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    os.system('chcp 65001 > nul 2>&1')
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Track acknowledgements for DEV/QAT (per session)
_acknowledged_environments = set()

AUTH_SNOWFLAKE_SSO = 'snowflake_sso'
AUTH_AZURE_AD_OAUTH = 'azure_ad_oauth'


def merge_azure_ad_config(config, env_config):
    """Merge top-level config.azure_ad with optional environments.<ENV>.azure_ad."""
    base = config.get('azure_ad') or {}
    override = (env_config or {}).get('azure_ad') or {}
    if not base and not override:
        return None
    merged = {**base, **override}
    scopes = merged.get('scopes') or merged.get('scope')
    if isinstance(scopes, str):
        scopes = [scopes]
    merged['scopes'] = scopes
    return merged


def validate_azure_ad_config(azure_cfg):
    if not azure_cfg:
        return False, 'Missing azure_ad in config (see config_sso.template.json).'
    if not str(azure_cfg.get('tenant_id', '')).strip():
        return False, 'azure_ad.tenant_id is required.'
    if not str(azure_cfg.get('client_id', '')).strip():
        return False, 'azure_ad.client_id is required.'
    scopes = azure_cfg.get('scopes')
    if not scopes or not isinstance(scopes, list) or not all(isinstance(s, str) and s.strip() for s in scopes):
        return False, 'azure_ad.scopes must be a non-empty list of strings (from Snowflake EXTERNAL_OAUTH / Entra setup).'
    return True, None


def acquire_azure_ad_access_token(azure_cfg, login_hint=None):
    """
    Interactive Microsoft Entra ID (Azure AD) login; returns an access token for Snowflake OAuth.
    Requires Snowflake security integration + Entra app registration; scopes come from your admin.
    """
    if msal is None:
        raise RuntimeError('Install msal (pip install msal) to use --auth azure_ad_oauth.')
    ok, err = validate_azure_ad_config(azure_cfg)
    if not ok:
        raise ValueError(err)
    app = msal.PublicClientApplication(
        str(azure_cfg['client_id']).strip(),
        authority=f"https://login.microsoftonline.com/{str(azure_cfg['tenant_id']).strip()}",
    )
    params = {'scopes': [s.strip() for s in azure_cfg['scopes']]}
    if login_hint:
        params['login_hint'] = login_hint.strip()
    result = app.acquire_token_interactive(**params)
    if result.get('access_token'):
        return result['access_token']
    msg = result.get('error_description') or result.get('error') or str(result)
    raise RuntimeError(f'Azure AD sign-in failed: {msg}')


def connect_to_snowflake(sf, user_email, auth_method=AUTH_SNOWFLAKE_SSO, azure_cfg=None):
    """
    auth_method:
      snowflake_sso — Snowflake externalbrowser (typical SSO; often redirects to Entra ID).
      azure_ad_oauth — Entra ID token via MSAL, then Snowflake connector authenticator='oauth'.
    """
    common = dict(
        user=user_email,
        account=sf['account'],
        warehouse=sf.get('warehouse'),
        database=sf.get('database'),
        schema=sf.get('schema'),
    )
    if sf.get('role'):
        common['role'] = str(sf['role']).strip()
    if auth_method == AUTH_AZURE_AD_OAUTH:
        token = acquire_azure_ad_access_token(azure_cfg, login_hint=user_email)
        return snowflake.connector.connect(**common, authenticator='oauth', token=token)
    try:
        return snowflake.connector.connect(**common, authenticator='externalbrowser')
    except snowflake.connector.errors.DatabaseError as e:
        if 'differs from the user currently logged in' in str(e):
            print('\n' + '=' * 60)
            print('ERROR: User Mismatch')
            print('=' * 60)
            print(f'\nThe email you entered: {user_email}')
            print('does not match the user you signed in as in your browser.')
            print('\nTo fix: re-run with the correct --user / config user_email, or sign out of the browser.')
            print('=' * 60)
        raise


def transform_query_for_environment(query, environment):
    """
    Transform database names in query based on environment.
    
    For DEV: DATABASE_NAME -> DATABASE_NAME_DEV
    For QAT: DATABASE_NAME -> DATABASE_NAME_QAT
    For PROD: DATABASE_NAME -> DATABASE_NAME (no change)
    
    Args:
        query: SQL query string
        environment: Environment name (DEV, QAT, PROD)
    
    Returns:
        str: Transformed query
    """
    if environment == 'PROD':
        # No transformation needed for PROD
        return query
    
    # Pattern to match database names in SQL
    # Matches: DATABASE_NAME.SCHEMA.TABLE or DATABASE_NAME.SCHEMA or just DATABASE_NAME
    # Avoids matching if already has _DEV or _QAT suffix
    
    if environment == 'DEV':
        # Replace DATABASE_NAME with DATABASE_NAME_DEV (if not already suffixed)
        # Match database names that don't already end with _DEV or _QAT
        query = re.sub(
            r'\b([A-Z][A-Z0-9_]*?)(?<!_DEV)(?<!_QAT)(?=\.|\s|$)',
            lambda m: f"{m.group(1)}_DEV" if not m.group(1).endswith('_DEV') and not m.group(1).endswith('_QAT') and '_DB' in m.group(1) else m.group(1),
            query
        )
    elif environment == 'QAT':
        # Replace DATABASE_NAME with DATABASE_NAME_QAT (if not already suffixed)
        query = re.sub(
            r'\b([A-Z][A-Z0-9_]*?)(?<!_DEV)(?<!_QAT)(?=\.|\s|$)',
            lambda m: f"{m.group(1)}_QAT" if not m.group(1).endswith('_DEV') and not m.group(1).endswith('_QAT') and '_DB' in m.group(1) else m.group(1),
            query
        )
    
    return query


def get_query_type(query):
    """
    Determine the type of SQL query (SELECT, INSERT, UPDATE, DELETE, etc.)
    
    Args:
        query: SQL query string
    
    Returns:
        str: Query type (SELECT, INSERT, UPDATE, DELETE, DROP, TRUNCATE, CREATE, ALTER, etc.)
    """
    # Remove comments and normalize whitespace
    query_normalized = re.sub(r'--.*?$', '', query, flags=re.MULTILINE)  # Remove single-line comments
    query_normalized = re.sub(r'/\*.*?\*/', '', query_normalized, flags=re.DOTALL)  # Remove multi-line comments
    query_normalized = query_normalized.strip()
    
    # Match first SQL keyword
    match = re.match(r'^\s*(WITH|SELECT|INSERT|UPDATE|DELETE|DROP|TRUNCATE|CREATE|ALTER|MERGE|COPY)\b', 
                     query_normalized, re.IGNORECASE)
    
    if match:
        keyword = match.group(1).upper()
        # WITH is typically used with SELECT
        if keyword == 'WITH':
            return 'SELECT'
        return keyword
    
    return 'UNKNOWN'


def confirm_query_execution(query, environment):
    """
    Confirm query execution based on query type and environment.
    
    For DEV/QAT: Warn once per session for non-SELECT queries
    For PROD: Always confirm for non-SELECT queries
    
    Args:
        query: SQL query string
        environment: Environment name (DEV, QAT, PROD)
    
    Returns:
        bool: True if user confirms, False otherwise
    """
    query_type = get_query_type(query)
    
    # SELECT queries don't need confirmation
    if query_type == 'SELECT':
        return True
    
    # For PROD: Always prompt
    if environment == 'PROD':
        print("\n" + "!" * 60)
        print("⚠️  WARNING: PRODUCTION ENVIRONMENT")
        print("!" * 60)
        print(f"Query Type: {query_type}")
        print("This is NOT a SELECT query and will modify PRODUCTION data!")
        print("\nQuery preview:")
        print("-" * 60)
        # Show first 10 lines of query
        query_lines = query.strip().split('\n')[:10]
        for line in query_lines:
            print(f"  {line}")
        if len(query.strip().split('\n')) > 10:
            print("  ... (query truncated)")
        print("-" * 60)
        
        response = input("\n⚠️  Type 'YES' (in capital letters) to proceed with PRODUCTION execution: ").strip()
        
        if response == 'YES':
            print("✓ Confirmed. Proceeding with PRODUCTION query execution...")
            return True
        else:
            print("✗ Execution cancelled by user.")
            return False
    
    # For DEV/QAT: Warn once per session
    if environment not in _acknowledged_environments:
        print("\n" + "!" * 60)
        print(f"⚠️  WARNING: {environment} Environment - Non-SELECT Query")
        print("!" * 60)
        print(f"Query Type: {query_type}")
        print(f"This query will modify data in {environment} environment.")
        print("\nQuery preview:")
        print("-" * 60)
        # Show first 10 lines of query
        query_lines = query.strip().split('\n')[:10]
        for line in query_lines:
            print(f"  {line}")
        if len(query.strip().split('\n')) > 10:
            print("  ... (query truncated)")
        print("-" * 60)
        
        response = input(f"\nType 'yes' to proceed (you won't be asked again for {environment} this session): ").strip().lower()
        
        if response == 'yes':
            _acknowledged_environments.add(environment)
            print(f"✓ Confirmed. Future {environment} queries will not prompt in this session.")
            return True
        else:
            print("✗ Execution cancelled by user.")
            return False
    
    # Already acknowledged for this environment
    return True


def run_query_with_sso(query_file, config_file='config_sso.json', output_file=None, user_email=None, environment=None, auth_method=AUTH_SNOWFLAKE_SSO):
    """
    Execute SQL query using SSO authentication and save to CSV.
    
    Args:
        query_file: Path to .sql file
        config_file: Path to config file with Snowflake connection details
        output_file: Where to save results (optional)
        user_email: User email for authentication (optional, will prompt if not provided)
        environment: Environment to use (DEV, QAT, PROD). If not provided, uses default from config
        auth_method: snowflake_sso (default) or azure_ad_oauth (Entra token + Snowflake OAuth)
    
    Returns:
        Path to output CSV file
    """
    # Load config
    try:
        with open(config_file) as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"Config file not found: {config_file}")
        print("Creating a template config file...")
        create_template_config(config_file)
        sys.exit(1)
    
    # Determine environment
    if 'environments' in config:
        # New multi-environment config
        if not environment:
            environment = config.get('default_environment', 'PROD')
        
        if environment not in config['environments']:
            print(f"Error: Environment '{environment}' not found in config.")
            print(f"Available environments: {', '.join(config['environments'].keys())}")
            sys.exit(1)
        
        env_config = config['environments'][environment]
    else:
        # Legacy single-environment config
        env_config = config
        environment = 'PROD'
    
    # Read query
    with open(query_file) as f:
        query = f.read()
    
    # Transform query for environment (adjust database names)
    original_query = query
    query = transform_query_for_environment(query, environment)
    
    # Show transformation if database names were changed
    if query != original_query and environment in ['DEV', 'QAT']:
        print("\n" + "=" * 60)
        print(f"🔄 Query transformed for {environment} environment")
        print("=" * 60)
        print("Database names automatically adjusted:")
        print(f"  Example: DATABASE_NAME → DATABASE_NAME_{environment}")
        print("=" * 60 + "\n")
    
    # Confirm query execution (safety check for non-SELECT queries)
    if not confirm_query_execution(query, environment):
        sys.exit(0)  # User cancelled
    
    # Get user email - check config first, then prompt if not provided
    if not user_email:
        # Try to get email from config
        user_email = config.get('user_email', '').strip()
        
        # If still not available, prompt
        if not user_email:
            print("\n" + "=" * 60)
            print("Snowflake SSO Authentication")
            print("=" * 60)
            user_email = input("\nEnter your T-Mobile email address: ").strip()
            
            if not user_email:
                print("Error: Email address is required for SSO authentication")
                sys.exit(1)
        else:
            print(f"\n✓ Using email from config: {user_email}")
    
    azure_cfg = merge_azure_ad_config(config, env_config)
    if auth_method == AUTH_AZURE_AD_OAUTH:
        ok, err = validate_azure_ad_config(azure_cfg)
        if not ok:
            print(f"\nError: {err}")
            print('Add azure_ad (tenant_id, client_id, scopes) to config_sso.json — ask Snowflake/Azure admin for OAuth scope values.')
            sys.exit(1)
        print("\n" + "=" * 60)
        print("Connecting to Snowflake using Azure AD (Entra) OAuth token...")
        print("=" * 60)
        print(f"Environment: {environment}")
        print(f"User (Snowflake login name): {user_email}")
        print("A Microsoft sign-in window will open.")
        print("=" * 60 + "\n")
    else:
        print("\n" + "=" * 60)
        print("Connecting to Snowflake using SSO authentication...")
        print("=" * 60)
        print(f"Environment: {environment}")
        print(f"User: {user_email}")
        print("A browser window will open for you to authenticate.")
        print("Please complete the authentication in your browser...")
        print("=" * 60 + "\n")
    
    sf = env_config['snowflake']
    conn = connect_to_snowflake(sf, user_email, auth_method=auth_method, azure_cfg=azure_cfg)
    
    print("✓ Successfully authenticated!")
    
    # Execute query
    print("Executing query...")
    cursor = conn.cursor()
    for stmt in sf.get('session_sql') or []:
        s = str(stmt).strip()
        if s:
            cursor.execute(s)
    cursor.execute(query)
    
    # Fetch results
    columns = [col[0] for col in cursor.description]
    df = pd.DataFrame.from_records(iter(cursor), columns=columns)
    
    print(f"✓ Query executed successfully. Retrieved {len(df)} rows.")
    
    # Save to CSV
    if not output_file:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"results_sso_{timestamp}.csv"
    
    df.to_csv(output_file, index=False)
    print(f"✓ Results saved to: {output_file}")
    
    # Cleanup
    cursor.close()
    conn.close()
    
    return output_file


def create_template_config(config_file):
    """Create a template configuration file for SSO authentication"""
    template = {
        "default_environment": "PROD",
        "environments": {
            "DEV": {
                "snowflake": {
                    "account": "tmobile.west-us-2.privatelink",
                    "warehouse": "YOUR_DEV_WAREHOUSE_NAME",
                    "database": "YOUR_DEV_DATABASE_NAME",
                    "schema": "YOUR_DEV_SCHEMA_NAME"
                }
            },
            "QAT": {
                "snowflake": {
                    "account": "tmobile.west-us-2.privatelink",
                    "warehouse": "YOUR_QAT_WAREHOUSE_NAME",
                    "database": "YOUR_QAT_DATABASE_NAME",
                    "schema": "YOUR_QAT_SCHEMA_NAME"
                }
            },
            "PROD": {
                "snowflake": {
                    "account": "tmobile.west-us-2.privatelink",
                    "warehouse": "YOUR_PROD_WAREHOUSE_NAME",
                    "database": "YOUR_PROD_DATABASE_NAME",
                    "schema": "YOUR_PROD_SCHEMA_NAME"
                }
            }
        },
        "azure_ad": {
            "tenant_id": "",
            "client_id": "",
            "scopes": []
        },
        "log_level": "INFO",
        "note": "For --auth azure_ad_oauth: set azure_ad.tenant_id, client_id (Entra public client), and scopes from Snowflake EXTERNAL_OAUTH. Default --auth snowflake_sso uses Snowflake browser SSO."
    }
    
    with open(config_file, 'w') as f:
        json.dump(template, f, indent=2)
    
    print(f"\nTemplate config file created: {config_file}")
    print("Please update it with your Snowflake connection details for each environment (DEV, QAT, PROD).")
    print("Note: User email will be prompted when you run the script.")


def run_direct_query(query_text, config_file='config_sso.json', output_file=None, user_email=None, environment=None, auth_method=AUTH_SNOWFLAKE_SSO):
    """
    Execute SQL query directly (without file) using SSO authentication
    
    Args:
        query_text: SQL query string
        config_file: Path to config file
        output_file: Where to save results (optional)
        user_email: User email for authentication (optional, will prompt if not provided)
        environment: Environment to use (DEV, QAT, PROD). If not provided, uses default from config
        auth_method: snowflake_sso (default) or azure_ad_oauth
    
    Returns:
        pandas.DataFrame: Query results
    """
    # Load config
    with open(config_file) as f:
        config = json.load(f)
    
    # Determine environment
    if 'environments' in config:
        # New multi-environment config
        if not environment:
            environment = config.get('default_environment', 'PROD')
        
        if environment not in config['environments']:
            print(f"Error: Environment '{environment}' not found in config.")
            print(f"Available environments: {', '.join(config['environments'].keys())}")
            sys.exit(1)
        
        env_config = config['environments'][environment]
    else:
        # Legacy single-environment config
        env_config = config
        environment = 'PROD'
    
    # Transform query for environment (adjust database names)
    original_query = query_text
    query_text = transform_query_for_environment(query_text, environment)
    
    # Show transformation if database names were changed
    if query_text != original_query and environment in ['DEV', 'QAT']:
        print("\n" + "=" * 60)
        print(f"🔄 Query transformed for {environment} environment")
        print("=" * 60)
        print("Database names automatically adjusted:")
        print(f"  Example: DATABASE_NAME → DATABASE_NAME_{environment}")
        print("=" * 60 + "\n")
    
    # Confirm query execution (safety check for non-SELECT queries)
    if not confirm_query_execution(query_text, environment):
        sys.exit(0)  # User cancelled
    
    # Get user email - check config first, then prompt if not provided
    if not user_email:
        # Try to get email from config
        user_email = config.get('user_email', '').strip()
        
        # If still not available, prompt
        if not user_email:
            print("\n" + "=" * 60)
            print("Snowflake SSO Authentication")
            print("=" * 60)
            user_email = input("\nEnter your T-Mobile email address: ").strip()
            
            if not user_email:
                print("Error: Email address is required for SSO authentication")
                sys.exit(1)
        else:
            print(f"\n✓ Using email from config: {user_email}")
    
    azure_cfg = merge_azure_ad_config(config, env_config)
    if auth_method == AUTH_AZURE_AD_OAUTH:
        ok, err = validate_azure_ad_config(azure_cfg)
        if not ok:
            print(f"\nError: {err}")
            sys.exit(1)
        print("\n" + "=" * 60)
        print("Connecting to Snowflake using Azure AD (Entra) OAuth token...")
        print("=" * 60)
        print(f"Environment: {environment}")
        print(f"User (Snowflake login name): {user_email}")
        print("A Microsoft sign-in window will open.")
        print("=" * 60 + "\n")
    else:
        print("\n" + "=" * 60)
        print("Connecting to Snowflake using SSO authentication...")
        print("=" * 60)
        print(f"Environment: {environment}")
        print(f"User: {user_email}")
        print("A browser window will open for you to authenticate.")
        print("=" * 60 + "\n")
    
    sf = env_config['snowflake']
    conn = connect_to_snowflake(sf, user_email, auth_method=auth_method, azure_cfg=azure_cfg)
    
    print("✓ Successfully authenticated!")
    
    # Execute query
    print("Executing query...")
    cursor = conn.cursor()
    for stmt in sf.get('session_sql') or []:
        s = str(stmt).strip()
        if s:
            cursor.execute(s)
    cursor.execute(query_text)
    
    # Fetch results
    columns = [col[0] for col in cursor.description]
    df = pd.DataFrame.from_records(iter(cursor), columns=columns)
    
    print(f"✓ Query executed successfully. Retrieved {len(df)} rows.")
    
    # Save to CSV if output file specified
    if output_file:
        df.to_csv(output_file, index=False)
        print(f"✓ Results saved to: {output_file}")
    
    # Cleanup
    cursor.close()
    conn.close()
    
    return df


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Snowflake Query Agent with SSO Authentication',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Will prompt for email address (uses default environment from config)
  python simple_agent_with_sso_auth.py query.sql
  
  # With output file
  python simple_agent_with_sso_auth.py query.sql output.csv
  
  # With user email (no prompt)
  python simple_agent_with_sso_auth.py query.sql output.csv --user your.email@t-mobile.com
  
  # Specify environment (DEV, QAT, or PROD)
  python simple_agent_with_sso_auth.py query.sql --env DEV
  python simple_agent_with_sso_auth.py query.sql output.csv --env QAT --user your.email@t-mobile.com
  
  # Azure AD (Entra) OAuth token → Snowflake (requires azure_ad in config from your admin)
  python simple_agent_with_sso_auth.py query.sql --env DEV --auth azure_ad_oauth
  
Note:
  - Default: browser SSO via Snowflake (externalbrowser); often still signs in with Microsoft.
  - azure_ad_oauth: Microsoft sign-in via MSAL, then connector uses OAuth token (needs tenant_id, client_id, scopes in config).
  - Make sure you have config_sso.json configured
  - User email will be prompted if not provided with --user
  - Environment defaults to the value in config (default_environment)
        """
    )
    
    parser.add_argument('query_file', help='Path to SQL query file')
    parser.add_argument('output_file', nargs='?', help='Output CSV file path (optional)')
    parser.add_argument('--user', '-u', dest='user_email', help='T-Mobile email address for SSO (optional, will prompt if not provided)')
    parser.add_argument('--config', '-c', default='config_sso.json', help='Config file path (default: config_sso.json)')
    parser.add_argument(
        '--env',
        '-e',
        dest='environment',
        choices=['DEV', 'QAT', 'PROD', 'PROD_PCMD'],
        help='Environment to use (DEV, QAT, PROD, PROD_PCMD for PRESENTATION.PCMD). Uses default from config if not specified',
    )
    parser.add_argument(
        '--auth',
        dest='auth_method',
        choices=[AUTH_SNOWFLAKE_SSO, AUTH_AZURE_AD_OAUTH],
        default=AUTH_SNOWFLAKE_SSO,
        help='snowflake_sso: Snowflake browser SSO (default). azure_ad_oauth: Entra ID token via MSAL + Snowflake OAuth.',
    )
    
    args = parser.parse_args()
    
    try:
        result = run_query_with_sso(
            query_file=args.query_file,
            config_file=args.config,
            output_file=args.output_file,
            user_email=args.user_email,
            environment=args.environment,
            auth_method=args.auth_method,
        )
        print(f"\n{'=' * 60}")
        print(f"✓ SUCCESS: Query execution completed!")
        print(f"✓ Output file: {result}")
        print(f"{'=' * 60}")
    except KeyboardInterrupt:
        print(f"\n{'=' * 60}")
        print("Operation cancelled by user")
        print(f"{'=' * 60}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{'=' * 60}")
        print(f"✗ ERROR: {e}")
        print(f"{'=' * 60}")
        sys.exit(1)

