CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    region TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1))
);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    status TEXT NOT NULL CHECK (status IN ('completed', 'cancelled')),
    ordered_on DATE NOT NULL,
    currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR'))
);
CREATE TABLE items (
    item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0)
);
CREATE TABLE refunds (
    refund_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    refunded_on DATE NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0)
);
