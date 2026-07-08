-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create application role (used by FastAPI, subject to RLS)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'operdai_app') THEN
        CREATE ROLE operdai_app LOGIN PASSWORD 'operdai_app_password';
    END IF;
END
$$;

-- Grant usage
GRANT USAGE ON SCHEMA public TO operdai_app;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO operdai_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO operdai_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO operdai_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO operdai_app;
