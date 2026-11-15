-- Runs only when the data directory is initialised for the first time.
-- Creates an isolated database for integration tests.
-- \gexec makes it a no-op if the database already exists.

SELECT 'CREATE DATABASE etlalchemy_test OWNER etlalchemy'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'etlalchemy_test')\gexec
