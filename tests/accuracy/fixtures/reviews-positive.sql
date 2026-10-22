CREATE TABLE product_reviews (id integer PRIMARY KEY, product_id integer REFERENCES products(id), rating integer NOT NULL CHECK(rating BETWEEN 1 AND 5));
COMMENT ON TABLE product_reviews IS 'Customer product reviews; one row per submitted review. Rating uses a one-to-five star scale.';
INSERT INTO product_reviews VALUES (1,1,5),(2,1,5),(3,1,2);
