"""Cedar Lane: the synthetic e-commerce database behind the free sample-data agent.

Every row is generated from one fixed seed, so the database and its reference answers are
rebuilt byte for byte. Nothing here is real: names come from short lists, emails use the
reserved example.com domain, and the shop does not exist.

    python build.py sql sample_ecommerce.sql                  # schema and data
    python build.py references reference_answers.json        # answers computed in Python

The reference answers are computed from the generated rows in plain Python, not by running
SQL, so `check_references.py` can compare them with SQL run on the loaded database: two
independent computations of the same business definitions (definitions.md).

Calendar 2025 only. No question depends on today's date, so answers never drift.
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

SEED = 20251231
YEAR = 2025


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


CATEGORIES = [
    # name, price range, return probability per delivered item, product nouns
    ("Electronics", (19, 449), 0.06, ["Wireless Earbuds", "Bluetooth Speaker", "Smart Watch",
                                      "USB-C Hub", "Portable Charger", "Webcam", "Keyboard",
                                      "Noise-Cancelling Headphones", "E-Reader", "Action Camera",
                                      "Smart Plug", "Monitor Arm", "Gaming Mouse", "Tablet Stand",
                                      "Dash Cam"]),
    ("Home & Kitchen", (12, 249), 0.04, ["Chef's Knife", "Cast Iron Skillet", "Coffee Grinder",
                                         "French Press", "Air Fryer", "Blender", "Cutting Board",
                                         "Dutch Oven", "Knife Block", "Kettle", "Food Storage Set",
                                         "Stand Mixer", "Toaster", "Spice Rack", "Bath Towels"]),
    ("Apparel", (15, 189), 0.14, ["Rain Jacket", "Wool Sweater", "Running Shoes", "Denim Jeans",
                                  "Linen Shirt", "Hoodie", "Chino Pants", "Leather Belt",
                                  "Winter Parka", "Sneakers", "Yoga Leggings", "Polo Shirt",
                                  "Beanie", "Hiking Boots", "Sundress"]),
    ("Beauty", (8, 89), 0.04, ["Face Serum", "Moisturizer", "Shampoo", "Conditioner", "Sunscreen",
                               "Lip Balm Set", "Hair Dryer", "Body Lotion", "Cleanser",
                               "Eye Cream", "Perfume", "Nail Kit", "Face Mask Pack",
                               "Beard Oil", "Hand Cream"]),
    ("Sports & Outdoors", (14, 329), 0.05, ["Yoga Mat", "Camping Tent", "Water Bottle",
                                            "Dumbbell Set", "Trekking Poles", "Sleeping Bag",
                                            "Bike Helmet", "Resistance Bands", "Foam Roller",
                                            "Hydration Pack", "Jump Rope", "Camp Stove",
                                            "Headlamp", "Kettlebell", "Cooler"]),
    ("Toys & Games", (9, 129), 0.03, ["Building Blocks", "Board Game", "Puzzle 1000pc",
                                      "Plush Bear", "Remote Control Car", "Card Game",
                                      "Science Kit", "Art Set", "Train Set", "Doll House",
                                      "Kite", "Magnetic Tiles", "Chess Set", "Dart Board",
                                      "Marble Run"]),
    ("Books", (7, 49), 0.02, ["Cookbook", "Travel Guide", "Mystery Novel", "Sci-Fi Novel",
                              "Business Handbook", "Gardening Guide", "Children's Atlas",
                              "Poetry Collection", "History of Maps", "Photography Basics",
                              "Language Workbook", "Biography", "Design Sketchbook",
                              "Field Guide to Birds", "Productivity Journal"]),
    ("Office", (6, 399), 0.03, ["Desk Lamp", "Office Chair", "Notebook Set", "Gel Pens",
                                "Desk Organizer", "Label Maker", "Standing Desk Converter",
                                "Whiteboard", "Paper Shredder", "Monitor Riser",
                                "Ergonomic Footrest", "Planner", "Filing Cabinet",
                                "Document Scanner", "Stapler"]),
]
ADJECTIVES = ["Aurora", "Summit", "Harbor", "Cedar", "Nova", "Atlas", "Willow", "Granite",
              "Lumen", "Pacific", "Meridian", "Orchard", "Vista", "Ember", "Juniper"]
RETURN_REASONS = {
    "Apparel": [("wrong size", 55), ("changed mind", 20), ("damaged in transit", 10),
                ("not as described", 15)],
    "Electronics": [("defective", 45), ("not as described", 20), ("changed mind", 20),
                    ("damaged in transit", 15)],
}
DEFAULT_REASONS = [("damaged in transit", 35), ("changed mind", 30), ("not as described", 20),
                   ("defective", 15)]
FIRST = ["Olivia", "Liam", "Emma", "Noah", "Ava", "Elijah", "Sophia", "Mateo", "Isabella",
         "Lucas", "Mia", "Levi", "Amelia", "Ezra", "Harper", "Asher", "Evelyn", "James",
         "Abigail", "Leo", "Emily", "Luca", "Ella", "Aiden", "Priya", "Arjun", "Mei", "Kenji",
         "Fatima", "Omar", "Chloe", "Diego", "Zoe", "Ravi", "Nora", "Samuel", "Leila", "Hugo",
         "Grace", "Daniel", "Aisha", "Theo", "Hannah", "Felix", "Sara", "Victor", "Ines", "Kai"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
        "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
        "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White",
        "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young",
        "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Patel",
        "Shah", "Kim", "Chen", "Tanaka", "Okafor", "Novak", "Rossi", "Silva", "Dubois"]
CITIES = [("New York", "NY", 14), ("Los Angeles", "CA", 11), ("Chicago", "IL", 8),
          ("Houston", "TX", 7), ("Phoenix", "AZ", 5), ("Philadelphia", "PA", 5),
          ("San Antonio", "TX", 4), ("San Diego", "CA", 4), ("Dallas", "TX", 5),
          ("Austin", "TX", 4), ("Seattle", "WA", 5), ("Denver", "CO", 4), ("Boston", "MA", 4),
          ("Atlanta", "GA", 4), ("Miami", "FL", 4), ("Portland", "OR", 3),
          ("Minneapolis", "MN", 3), ("Nashville", "TN", 3), ("Columbus", "OH", 3)]
CHANNELS = [("organic_search", 30), ("paid_search", 22), ("social", 18), ("email", 10),
            ("referral", 12), ("marketplace", 8)]
# Orders a customer places in 2025 depend on how they found us: referred and email
# customers come back more; marketplace shoppers mostly buy once.
CHANNEL_LOYALTY = {"organic_search": 1.0, "paid_search": 0.85, "social": 0.8, "email": 1.35,
                   "referral": 1.3, "marketplace": 0.6}
MONTH_WEIGHT = [0.8, 0.75, 0.9, 0.9, 1.0, 0.95, 0.9, 1.0, 1.0, 1.05, 1.55, 1.85]
METHODS_CONSUMER = [("card", 62), ("paypal", 22), ("apple_pay", 11), ("gift_card", 5)]
METHODS_BUSINESS = [("card", 45), ("bank_transfer", 40), ("paypal", 15)]


def pick(rng: random.Random, weighted):
    values, weights = zip(*weighted)
    return rng.choices(values, weights=weights, k=1)[0]


@dataclass
class World:
    categories: list
    products: list
    customers: list
    orders: list
    items: list
    payments: list
    returns: list


def generate() -> World:
    rng = random.Random(SEED)
    categories, products = [], []
    for cid, (name, (lo, hi), _, nouns) in enumerate(CATEGORIES, start=1):
        categories.append({"category_id": cid, "name": name})
        for noun in nouns:
            pid = len(products) + 1
            price = money(round(rng.uniform(lo, hi)) - 0.01)
            products.append({
                "product_id": pid, "sku": f"CL-{cid:02d}{pid:04d}",
                "name": f"{rng.choice(ADJECTIVES)} {noun}", "category_id": cid,
                "list_price": price, "unit_cost": money(price * Decimal(str(rng.uniform(0.42, 0.68)))),
                "launched_on": date(2023, 1, 1) + timedelta(days=rng.randint(0, 900)),
                "popularity": rng.paretovariate(1.6),
            })

    customers, used_names = [], set()
    while len(customers) < 2400:
        first, last = rng.choice(FIRST), rng.choice(LAST)
        if (first, last) in used_names and rng.random() < 0.85:
            continue
        used_names.add((first, last))
        cid = len(customers) + 1
        city, state, _ = pick(rng, [((c, s, w), w) for c, s, w in CITIES])
        segment = "business" if rng.random() < 0.14 else "consumer"
        customers.append({
            "customer_id": cid, "first_name": first, "last_name": last,
            "email": f"{first.lower()}.{last.lower()}{cid}@example.com",
            "city": city, "state": state, "segment": segment,
            "acquisition_channel": pick(rng, CHANNELS),
            "signup_date": date(2023, 6, 1) + timedelta(days=rng.randint(0, 900)),
        })

    days = [date(YEAR, 1, 1) + timedelta(days=i) for i in range(365)]
    day_weight = [MONTH_WEIGHT[d.month - 1] * (1.15 if d.weekday() >= 5 else 1.0) for d in days]
    # Cheaper products sell more often; a few products in every price band are hits.
    weights_products = [p["popularity"] / float(p["list_price"]) ** 0.5 for p in products]
    orders, items, payments, returns = [], [], [], []

    for cust in customers:
        eligible = [(d, w) for d, w in zip(days, day_weight) if d >= cust["signup_date"]]
        if not eligible:
            continue
        # Expected 2025 orders scale with how much of the year the customer was signed up,
        # so late sign-ups do not crowd their orders into December.
        base = 4.5 if cust["segment"] == "business" else 2.2
        mean = base * CHANNEL_LOYALTY[cust["acquisition_channel"]] * len(eligible) / 365
        n = int(rng.expovariate(1 / mean) + 0.5) if mean > 0 else 0
        if n == 0:
            continue
        for _ in range(min(n, 30)):
            day = pick(rng, eligible)
            ts = datetime(day.year, day.month, day.day, rng.randint(7, 23), rng.randint(0, 59),
                          rng.randint(0, 59))
            oid = len(orders) + 1
            lines = []
            for _ in range(rng.choices([1, 2, 3, 4], weights=[50, 30, 14, 6])[0]):
                product = rng.choices(products, weights=weights_products)[0]
                qty = rng.choices([1, 2, 3, 5, 10], weights=[40, 25, 18, 11, 6])[0]                     if cust["segment"] == "business" else rng.choices([1, 2, 3], weights=[78, 17, 5])[0]
                lines.append((product, qty))
            subtotal = sum((p["list_price"] * q for p, q in lines), Decimal("0"))
            discount = Decimal("0")
            if rng.random() < 0.22:
                discount = money(subtotal * Decimal(rng.choice(["0.10", "0.15", "0.20"])))
            shipping = Decimal("0.00") if subtotal >= 75 else Decimal("6.99")
            roll = rng.random()
            if roll < 0.04:
                status = "cancelled"
            elif day >= date(YEAR, 12, 27):
                status = "processing" if roll < 0.5 else "shipped"
            elif day >= date(YEAR, 12, 20):
                status = "shipped" if roll < 0.6 else "delivered"
            else:
                status = "delivered"
            order = {
                "order_id": oid, "customer_id": cust["customer_id"], "ordered_at": ts,
                "status": status, "channel": pick(rng, [("web", 58), ("mobile_app", 34),
                                                        ("phone", 8)]),
                "subtotal": money(subtotal), "discount_amount": discount,
                "shipping_fee": shipping, "total_amount": money(subtotal - discount + shipping),
            }
            orders.append(order)
            for product, qty in lines:
                iid = len(items) + 1
                line_total = money(product["list_price"] * qty)
                items.append({"order_item_id": iid, "order_id": oid,
                              "product_id": product["product_id"], "quantity": qty,
                              "unit_price": product["list_price"], "line_total": line_total})
                category = CATEGORIES[product["category_id"] - 1]
                if status == "delivered" and rng.random() < category[2]:
                    requested = day + timedelta(days=rng.randint(3, 28))
                    rstatus = pick(rng, [("approved", 84), ("rejected", 11), ("pending", 5)])
                    returns.append({
                        "return_id": len(returns) + 1, "order_item_id": iid,
                        "requested_on": requested,
                        "reason": pick(rng, RETURN_REASONS.get(category[0], DEFAULT_REASONS)),
                        "status": rstatus,
                        "refund_amount": line_total if rstatus == "approved" else Decimal("0.00"),
                    })
            if status == "cancelled":
                continue
            methods = METHODS_BUSINESS if cust["segment"] == "business" else METHODS_CONSUMER
            method = pick(rng, methods)
            if rng.random() < 0.03:
                payments.append({"payment_id": len(payments) + 1, "order_id": oid,
                                 "paid_at": ts + timedelta(minutes=1), "method": method,
                                 "amount": order["total_amount"], "status": "failed"})
                method = pick(rng, methods)
            payments.append({"payment_id": len(payments) + 1, "order_id": oid,
                             "paid_at": ts + timedelta(minutes=rng.randint(2, 30)),
                             "method": method, "amount": order["total_amount"],
                             "status": "captured"})
    return World(categories, products, customers, orders, items, payments, returns)


# ── SQL ──────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE categories (
    category_id integer PRIMARY KEY,
    name text NOT NULL UNIQUE
);
CREATE TABLE products (
    product_id integer PRIMARY KEY,
    sku text NOT NULL UNIQUE,
    name text NOT NULL,
    category_id integer NOT NULL REFERENCES categories,
    list_price numeric(10,2) NOT NULL,
    unit_cost numeric(10,2) NOT NULL,
    launched_on date NOT NULL
);
CREATE TABLE customers (
    customer_id integer PRIMARY KEY,
    first_name text NOT NULL,
    last_name text NOT NULL,
    email text NOT NULL UNIQUE,
    city text NOT NULL,
    state text NOT NULL,
    segment text NOT NULL CHECK (segment IN ('consumer', 'business')),
    acquisition_channel text NOT NULL,
    signup_date date NOT NULL
);
CREATE TABLE orders (
    order_id integer PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES customers,
    ordered_at timestamp NOT NULL,
    status text NOT NULL CHECK (status IN ('processing', 'shipped', 'delivered', 'cancelled')),
    channel text NOT NULL,
    subtotal numeric(12,2) NOT NULL,
    discount_amount numeric(12,2) NOT NULL,
    shipping_fee numeric(12,2) NOT NULL,
    total_amount numeric(12,2) NOT NULL
);
CREATE TABLE order_items (
    order_item_id integer PRIMARY KEY,
    order_id integer NOT NULL REFERENCES orders,
    product_id integer NOT NULL REFERENCES products,
    quantity integer NOT NULL,
    unit_price numeric(10,2) NOT NULL,
    line_total numeric(12,2) NOT NULL
);
CREATE TABLE payments (
    payment_id integer PRIMARY KEY,
    order_id integer NOT NULL REFERENCES orders,
    paid_at timestamp NOT NULL,
    method text NOT NULL,
    amount numeric(12,2) NOT NULL,
    status text NOT NULL CHECK (status IN ('captured', 'failed'))
);
CREATE TABLE returns (
    return_id integer PRIMARY KEY,
    order_item_id integer NOT NULL REFERENCES order_items,
    requested_on date NOT NULL,
    reason text NOT NULL,
    status text NOT NULL CHECK (status IN ('approved', 'rejected', 'pending')),
    refund_amount numeric(12,2) NOT NULL
);
CREATE INDEX ON orders (customer_id);
CREATE INDEX ON orders (ordered_at);
CREATE INDEX ON order_items (order_id);
CREATE INDEX ON order_items (product_id);
CREATE INDEX ON payments (order_id);
CREATE INDEX ON returns (order_item_id);
"""

COLUMNS = {
    "categories": ["category_id", "name"],
    "products": ["product_id", "sku", "name", "category_id", "list_price", "unit_cost",
                 "launched_on"],
    "customers": ["customer_id", "first_name", "last_name", "email", "city", "state", "segment",
                  "acquisition_channel", "signup_date"],
    "orders": ["order_id", "customer_id", "ordered_at", "status", "channel", "subtotal",
               "discount_amount", "shipping_fee", "total_amount"],
    "order_items": ["order_item_id", "order_id", "product_id", "quantity", "unit_price",
                    "line_total"],
    "payments": ["payment_id", "order_id", "paid_at", "method", "amount", "status"],
    "returns": ["return_id", "order_item_id", "requested_on", "reason", "status",
                "refund_amount"],
}


def literal(value) -> str:
    if isinstance(value, (int, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return f"'{value.isoformat(sep=' ')}'"
    if isinstance(value, date):
        return f"'{value.isoformat()}'"
    return "'" + str(value).replace("'", "''") + "'"


def to_sql(world: World) -> str:
    out = ["-- Cedar Lane: synthetic online-shop data, generated by build.py (seed "
           f"{SEED}). Not real people or orders.", "BEGIN;", SCHEMA.strip()]
    for table, cols in COLUMNS.items():
        rows = getattr(world, {"order_items": "items"}.get(table, table))
        for start in range(0, len(rows), 500):
            values = ",\n".join("(" + ", ".join(literal(r[c]) for c in cols) + ")"
                                for r in rows[start:start + 500])
            out.append(f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n{values};")
    out.append("ANALYZE;")
    out.append("COMMIT;")
    return "\n".join(out) + "\n"


# ── Reference answers (plain Python over the generated rows) ─────────────────

def references(world: World) -> list:
    orders = {o["order_id"]: o for o in world.orders}
    live = [o for o in world.orders if o["status"] != "cancelled"]
    customers = {c["customer_id"]: c for c in world.customers}
    products = {p["product_id"]: p for p in world.products}
    categories = {c["category_id"]: c["name"] for c in world.categories}
    items = {i["order_item_id"]: i for i in world.items}

    spend = defaultdict(Decimal)
    for o in live:
        spend[o["customer_id"]] += o["total_amount"]
    top = sorted(spend.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    top_rows = [[f"{customers[c]['first_name']} {customers[c]['last_name']}", str(v)] for c, v in top]

    monthly = defaultdict(Decimal)
    for o in live:
        monthly[o["ordered_at"].month] += o["total_amount"]

    delivered_items = Counter()
    returned_items = Counter()
    for i in world.items:
        if orders[i["order_id"]]["status"] == "delivered":
            delivered_items[categories[products[i["product_id"]]["category_id"]]] += 1
    for r in world.returns:
        if r["status"] == "approved":
            item = items[r["order_item_id"]]
            returned_items[categories[products[item["product_id"]]["category_id"]]] += 1
    return_rate = sorted(((cat, round(100 * returned_items[cat] / n, 1))
                          for cat, n in delivered_items.items()), key=lambda kv: -kv[1])

    reasons = Counter(r["reason"] for r in world.returns).most_common()

    captured = Counter(p["method"] for p in world.payments if p["status"] == "captured")
    total_captured = sum(captured.values())
    method_share = [[m, n, round(100 * n / total_captured, 1)] for m, n in captured.most_common()]

    by_channel = defaultdict(lambda: [Decimal("0"), 0])
    for o in live:
        bucket = by_channel[customers[o["customer_id"]]["acquisition_channel"]]
        bucket[0] += o["total_amount"]
        bucket[1] += 1
    aov = sorted(((ch, str(money(v / n))) for ch, (v, n) in by_channel.items()),
                 key=lambda kv: -Decimal(kv[1]))

    cancelled = Counter(f"Q{(o['ordered_at'].month - 1) // 3 + 1}"
                        for o in world.orders if o["status"] == "cancelled")

    return [
        {"question": "Who are our top five customers by total spend?",
         "definition": "customer spend = sum of orders.total_amount over non-cancelled orders",
         "columns": ["customer", "total_spend"], "rows": top_rows,
         "reference_sql": """
            SELECT c.first_name || ' ' || c.last_name AS customer, SUM(o.total_amount) AS total_spend
            FROM orders o JOIN customers c USING (customer_id)
            WHERE o.status <> 'cancelled'
            GROUP BY c.customer_id, customer ORDER BY total_spend DESC, c.customer_id LIMIT 5"""},
        {"question": "Show a bar chart of the top five customers by total spend.",
         "definition": "same as the previous question; expect a simple bar chart, one bar per customer",
         "columns": ["customer", "total_spend"], "rows": top_rows, "chart": "bar",
         "reference_sql": None},
        {"question": "How did monthly revenue change across 2025?",
         "definition": "revenue = sum of orders.total_amount over non-cancelled orders, by order month",
         "columns": ["month", "revenue"],
         "rows": [[m, str(monthly[m])] for m in range(1, 13)],
         "reference_sql": """
            SELECT EXTRACT(MONTH FROM ordered_at)::int AS month, SUM(total_amount) AS revenue
            FROM orders WHERE status <> 'cancelled' GROUP BY 1 ORDER BY 1"""},
        {"question": "Which product categories have the highest return rate?",
         "definition": "return rate = approved returns / order items on delivered orders, per category, in percent",
         "columns": ["category", "return_rate_pct"],
         "rows": [[c, str(r)] for c, r in return_rate],
         "reference_sql": """
            SELECT cat.name AS category,
                   ROUND(100.0 * COUNT(r.return_id) FILTER (WHERE r.status = 'approved')
                         / COUNT(DISTINCT oi.order_item_id), 1) AS return_rate_pct
            FROM order_items oi
            JOIN orders o USING (order_id)
            JOIN products p USING (product_id)
            JOIN categories cat USING (category_id)
            LEFT JOIN returns r USING (order_item_id)
            WHERE o.status = 'delivered'
            GROUP BY cat.name ORDER BY return_rate_pct DESC"""},
        {"question": "What are the most common reasons for returns?",
         "definition": "count of all return requests by reason",
         "columns": ["reason", "returns"], "rows": [[r, n] for r, n in reasons],
         "reference_sql": """
            SELECT reason, COUNT(*) AS returns FROM returns GROUP BY reason ORDER BY returns DESC"""},
        {"question": "What share of orders was paid with each payment method?",
         "definition": "captured payments by method, as a percent of all captured payments",
         "columns": ["method", "orders", "share_pct"], "rows": method_share,
         "reference_sql": """
            SELECT method, COUNT(*) AS orders,
                   ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS share_pct
            FROM payments WHERE status = 'captured' GROUP BY method ORDER BY orders DESC"""},
        {"question": "Which acquisition channel brings customers with the highest average order value?",
         "definition": "average order value = average orders.total_amount over non-cancelled orders, by the customer's acquisition_channel",
         "columns": ["acquisition_channel", "average_order_value"], "rows": [list(r) for r in aov],
         "reference_sql": """
            SELECT c.acquisition_channel, ROUND(AVG(o.total_amount), 2) AS average_order_value
            FROM orders o JOIN customers c USING (customer_id)
            WHERE o.status <> 'cancelled'
            GROUP BY c.acquisition_channel ORDER BY average_order_value DESC"""},
        {"question": "How many orders were cancelled in each quarter of 2025?",
         "definition": "count of orders with status 'cancelled', by quarter of ordered_at",
         "columns": ["quarter", "cancelled_orders"],
         "rows": [[q, cancelled[q]] for q in ("Q1", "Q2", "Q3", "Q4")],
         "reference_sql": """
            SELECT 'Q' || EXTRACT(QUARTER FROM ordered_at)::int AS quarter, COUNT(*) AS cancelled_orders
            FROM orders WHERE status = 'cancelled' GROUP BY 1 ORDER BY 1"""},
    ]


def summary(world: World) -> dict:
    return {name: len(getattr(world, attr)) for name, attr in (
        ("categories", "categories"), ("products", "products"), ("customers", "customers"),
        ("orders", "orders"), ("order_items", "items"), ("payments", "payments"),
        ("returns", "returns"))}


if __name__ == "__main__":
    # Written as UTF-8 with LF line endings to the named file, so the output is identical on
    # every platform (a shell redirect on Windows would re-encode it).
    if len(sys.argv) != 3 or sys.argv[1] not in ("sql", "references"):
        sys.exit("usage: build.py sql|references OUTPUT_FILE")
    world = generate()
    if sys.argv[1] == "sql":
        text = to_sql(world)
    else:
        text = json.dumps({"seed": SEED, "row_counts": summary(world),
                           "answers": references(world)}, indent=2, default=str) + "\n"
    with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
