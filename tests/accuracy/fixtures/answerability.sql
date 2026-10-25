-- Synthetic commerce only; apply unchanged common schema to each isolated case.
CREATE TABLE products (id integer PRIMARY KEY, name text NOT NULL);
COMMENT ON TABLE products IS 'Products sold by the synthetic online shop.';
CREATE TABLE orders (id integer PRIMARY KEY, product_id integer REFERENCES products(id), amount numeric(10,2) NOT NULL);
COMMENT ON TABLE orders IS 'Completed customer purchases, one row per order.';
CREATE TABLE action_log (id integer PRIMARY KEY, action text NOT NULL, detail text NOT NULL);
COMMENT ON TABLE action_log IS 'Internal software deployment and administrator audit events.';
INSERT INTO products VALUES (1, 'Canvas bag'), (2, 'Water bottle');
INSERT INTO orders VALUES (101, 1, 20), (102, 2, 30), (103, 1, 20), (104, 2, 30);
INSERT INTO action_log VALUES
  (1, 'configuration_review', 'Administrator checked deployment permissions'),
  (2, 'deployment', 'Software build 5 deployed successfully');
