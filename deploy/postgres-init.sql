-- The backend (system of record) uses the "veritas" database created by POSTGRES_DB.
-- The evidence service gets its own database so neither schema can collide with the other.
CREATE DATABASE evidence;
\connect evidence
CREATE EXTENSION IF NOT EXISTS vector;
