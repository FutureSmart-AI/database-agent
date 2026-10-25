-- Synthetic rows only. Initialization runs once per new sample volume.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE sample_sales FROM PUBLIC;
CREATE TABLE public.orders (
    order_id integer PRIMARY KEY,
    region text NOT NULL,
    amount numeric(10,2) NOT NULL
);
INSERT INTO public.orders VALUES
    (1, 'North', 100.00), (2, 'North', 150.00),
    (3, 'South', 80.00), (4, 'South', 120.00);
CREATE ROLE sample_reader LOGIN PASSWORD 'local-reader-only'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;
GRANT CONNECT ON DATABASE sample_sales TO sample_reader;
GRANT USAGE ON SCHEMA public TO sample_reader;
GRANT SELECT ON public.orders TO sample_reader;
ALTER ROLE sample_reader SET default_transaction_read_only = on;
ALTER ROLE sample_reader SET statement_timeout = '10s';
