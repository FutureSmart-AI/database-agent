"""Riverbend Clinics: the second synthetic database of the model evaluation.

Chosen to be structurally unlike Cedar Lane (deploy/demo/ecommerce): a many-to-many
clinician/location assignment, two grains that must be aggregated separately before they
meet (shift minutes vs appointment minutes), invoices paid in several partial payments,
patients identified only through appointments, and one question the schema cannot answer.

Every row comes from one fixed seed, so the database and its reference answers rebuild
byte for byte. Nothing is real: names come from short lists, and the clinics do not exist.

    python build.py sql riverbend.sql
    python build.py references reference_answers.json

Reference answers are computed here in plain Python from the generated rows; the model
evaluation also runs each answer's `reference_sql` on the loaded database and requires the
two to agree before any model is graded (see ../../provision.py). January-June 2025 only;
no question depends on today's date.
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

SEED = 20250630
START, END = date(2025, 1, 1), date(2025, 6, 30)


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pct(numerator, denominator) -> Decimal:
    return (Decimal(100) * numerator / denominator).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


LOCATIONS = [("Riverbend Downtown", "Portland"), ("Riverbend Eastside", "Portland"),
             ("Riverbend Lakeview", "Beaverton")]
# name, minutes, price; the price is what an invoice charges for one completed visit
SERVICES = [("General consultation", 20, "95.00"), ("Physiotherapy session", 45, "140.00"),
            ("Dermatology review", 30, "180.00"), ("Nutrition counselling", 40, "110.00"),
            ("Vaccination", 15, "60.00"), ("Mental health session", 50, "160.00")]
CLINICIANS = [  # name, specialty, services they deliver (indexes into SERVICES)
    ("Dr. Hana Okafor", "General practice", [0, 4]),
    ("Dr. Marco Rossi", "General practice", [0, 4]),
    ("Dr. Leila Haddad", "Dermatology", [2, 0]),
    ("Sam Turner", "Physiotherapy", [1]),
    ("Ines Novak", "Physiotherapy", [1]),
    ("Priya Raman", "Dietetics", [3]),
    ("Dr. Felix Brandt", "Psychology", [5]),
    ("Dr. Aiko Tanaka", "General practice", [0, 4, 2]),
]
# clinician index -> locations they work at (many-to-many)
ASSIGNMENTS = {0: [0, 1], 1: [1], 2: [0, 2], 3: [0, 2], 4: [1], 5: [0, 1, 2], 6: [2], 7: [0]}
# Dr. Marco Rossi is on leave for June and Ines Novak leaves at the end of May: both have
# no completed visits in June, which one question depends on.
LAST_DAY = {1: date(2025, 5, 31), 4: date(2025, 5, 31)}
FIRST = ["Olivia", "Liam", "Emma", "Noah", "Ava", "Mateo", "Mia", "Levi", "Amelia", "Ezra",
         "Harper", "Asher", "Evelyn", "James", "Leo", "Ella", "Priya", "Arjun", "Mei", "Kenji",
         "Fatima", "Omar", "Chloe", "Diego", "Zoe", "Ravi", "Nora", "Samuel", "Grace", "Theo"]
LAST = ["Smith", "Garcia", "Miller", "Davis", "Lopez", "Wilson", "Anderson", "Taylor", "Moore",
        "Martin", "Lee", "Perez", "White", "Harris", "Clark", "Lewis", "Walker", "Young", "Allen",
        "King", "Nguyen", "Hill", "Patel", "Shah", "Kim", "Chen", "Silva", "Dubois"]
PAYERS = [("insurance", 60), ("self_pay", 30), ("employer", 10)]


def pick(rng: random.Random, weighted):
    values, weights = zip(*weighted)
    return rng.choices(values, weights=weights, k=1)[0]


@dataclass
class World:
    locations: list
    services: list
    clinicians: list
    clinician_locations: list
    shifts: list
    patients: list
    appointments: list
    invoices: list
    payments: list


def workdays():
    day = START
    while day <= END:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def generate() -> World:
    rng = random.Random(SEED)
    locations = [{"location_id": i + 1, "name": n, "city": c} for i, (n, c) in enumerate(LOCATIONS)]
    services = [{"service_id": i + 1, "name": n, "duration_min": m, "price": Decimal(p)}
                for i, (n, m, p) in enumerate(SERVICES)]
    clinicians = [{"clinician_id": i + 1, "full_name": n, "specialty": s}
                  for i, (n, s, _) in enumerate(CLINICIANS)]
    clinician_locations = [{"clinician_id": c + 1, "location_id": l + 1}
                           for c, locs in ASSIGNMENTS.items() for l in locs]

    shifts = []
    for day in workdays():
        for c, locs in ASSIGNMENTS.items():
            if day > LAST_DAY.get(c, END) or rng.random() < 0.15:
                continue
            loc = locs[(day.toordinal() + c) % len(locs)]
            start_hour = rng.choice([8, 9, 12])
            hours = rng.choice([4, 6, 8]) if start_hour < 12 else 5
            shifts.append({"shift_id": len(shifts) + 1, "clinician_id": c + 1, "location_id": loc + 1,
                           "shift_date": day, "starts_at": time(start_hour, 0),
                           "ends_at": time(start_hour + hours, 0)})

    # Patients join the practice through the half-year and mostly stay with one clinician,
    # so "new patients per month" and "seen by more than one clinician" are not trivial.
    # Neither the join date nor the regular clinician is stored: both show only through
    # appointments.
    patients, joined, regular = [], {}, {}
    span = (END - START).days
    for i in range(900):
        pid = i + 1
        patients.append({"patient_id": pid, "first_name": rng.choice(FIRST),
                         "last_name": rng.choice(LAST), "birth_year": rng.randint(1945, 2015),
                         "payer_type": pick(rng, PAYERS)})
        joined[pid] = START + timedelta(days=int(span * rng.random() ** 1.6))
        regular[pid] = rng.randint(1, len(CLINICIANS))

    appointments = []
    for shift in shifts:
        c = shift["clinician_id"] - 1
        cursor = datetime.combine(shift["shift_date"], shift["starts_at"])
        end = datetime.combine(shift["shift_date"], shift["ends_at"])
        while True:
            service = services[rng.choice(CLINICIANS[c][2])]
            slot_end = cursor + timedelta(minutes=service["duration_min"])
            if slot_end > end:
                break
            if rng.random() < 0.45:
                lead = rng.choice([0, 1, 2, 3, 5, 7, 10, 14, 21, 30])
                booked = cursor - timedelta(days=lead, hours=rng.randint(1, 9))
                status = pick(rng, [("completed", 82), ("no_show", 9), ("cancelled", 9)])
                eligible = [p for p in joined if joined[p] <= shift["shift_date"]]
                own = [p for p in eligible if regular[p] == c + 1]
                patient = rng.choice(own if own and rng.random() < 0.8 else eligible)
                appointments.append({
                    "appointment_id": len(appointments) + 1,
                    "patient_id": patient, "clinician_id": c + 1,
                    "location_id": shift["location_id"], "service_id": service["service_id"],
                    "booked_at": booked, "starts_at": cursor,
                    "duration_min": service["duration_min"], "status": status})
            cursor = slot_end + timedelta(minutes=rng.choice([0, 5, 10]))

    invoices, payments = [], []
    for a in appointments:
        if a["status"] != "completed":
            continue
        price = services[a["service_id"] - 1]["price"]
        invoice = {"invoice_id": len(invoices) + 1, "appointment_id": a["appointment_id"],
                   "issued_on": a["starts_at"].date(), "amount": price}
        invoices.append(invoice)
        outcome = rng.random()
        if outcome < 0.70:
            parts = [price]
        elif outcome < 0.88:
            first = money(price * Decimal(rng.choice(["0.2", "0.5", "0.8"])))
            parts = [first, price - first]
        elif outcome < 0.96:
            parts = [money(price * Decimal(rng.choice(["0.3", "0.6"])))]  # still owed
        else:
            parts = []  # unpaid
        for k, amount in enumerate(parts):
            payments.append({"payment_id": len(payments) + 1, "invoice_id": invoice["invoice_id"],
                             "paid_on": invoice["issued_on"] + timedelta(days=3 + 9 * k),
                             "amount": amount})
    return World(locations, services, clinicians, clinician_locations, shifts, patients,
                 appointments, invoices, payments)


SCHEMA = """
CREATE TABLE locations (location_id int PRIMARY KEY, name text NOT NULL, city text NOT NULL);
CREATE TABLE services (service_id int PRIMARY KEY, name text NOT NULL,
    duration_min int NOT NULL, price numeric(8,2) NOT NULL);
CREATE TABLE clinicians (clinician_id int PRIMARY KEY, full_name text NOT NULL, specialty text NOT NULL);
CREATE TABLE clinician_locations (clinician_id int REFERENCES clinicians,
    location_id int REFERENCES locations, PRIMARY KEY (clinician_id, location_id));
CREATE TABLE shifts (shift_id int PRIMARY KEY, clinician_id int NOT NULL REFERENCES clinicians,
    location_id int NOT NULL REFERENCES locations, shift_date date NOT NULL,
    starts_at time NOT NULL, ends_at time NOT NULL);
CREATE TABLE patients (patient_id int PRIMARY KEY, first_name text NOT NULL, last_name text NOT NULL,
    birth_year int NOT NULL, payer_type text NOT NULL);
CREATE TABLE appointments (appointment_id int PRIMARY KEY, patient_id int NOT NULL REFERENCES patients,
    clinician_id int NOT NULL REFERENCES clinicians, location_id int NOT NULL REFERENCES locations,
    service_id int NOT NULL REFERENCES services, booked_at timestamp NOT NULL,
    starts_at timestamp NOT NULL, duration_min int NOT NULL, status text NOT NULL);
CREATE TABLE invoices (invoice_id int PRIMARY KEY, appointment_id int NOT NULL UNIQUE REFERENCES appointments,
    issued_on date NOT NULL, amount numeric(8,2) NOT NULL);
CREATE TABLE payments (payment_id int PRIMARY KEY, invoice_id int NOT NULL REFERENCES invoices,
    paid_on date NOT NULL, amount numeric(8,2) NOT NULL);
"""

COLUMNS = {
    "locations": ["location_id", "name", "city"],
    "services": ["service_id", "name", "duration_min", "price"],
    "clinicians": ["clinician_id", "full_name", "specialty"],
    "clinician_locations": ["clinician_id", "location_id"],
    "shifts": ["shift_id", "clinician_id", "location_id", "shift_date", "starts_at", "ends_at"],
    "patients": ["patient_id", "first_name", "last_name", "birth_year", "payer_type"],
    "appointments": ["appointment_id", "patient_id", "clinician_id", "location_id", "service_id",
                     "booked_at", "starts_at", "duration_min", "status"],
    "invoices": ["invoice_id", "appointment_id", "issued_on", "amount"],
    "payments": ["payment_id", "invoice_id", "paid_on", "amount"],
}


def literal(value) -> str:
    if isinstance(value, (int, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return f"'{value.isoformat(sep=' ')}'"
    if isinstance(value, (date, time)):
        return f"'{value.isoformat()}'"
    return "'" + str(value).replace("'", "''") + "'"


def to_sql(world: World) -> str:
    out = ["-- Riverbend Clinics: synthetic data generated by build.py (seed "
           f"{SEED}). Not real people or visits.", "BEGIN;", SCHEMA.strip()]
    for table, cols in COLUMNS.items():
        rows = getattr(world, table)
        for start in range(0, len(rows), 500):
            values = ",\n".join("(" + ", ".join(literal(r[c]) for c in cols) + ")"
                                for r in rows[start:start + 500])
            out.append(f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n{values};")
    out.append("ANALYZE;")
    out.append("COMMIT;")
    return "\n".join(out) + "\n"


# ── Reference answers (plain Python over the generated rows) ─────────────────

def references(world: World) -> list:
    loc = {l["location_id"]: l["name"] for l in world.locations}
    svc = {s["service_id"]: s["name"] for s in world.services}
    doc = {c["clinician_id"]: c["full_name"] for c in world.clinicians}
    patients = {p["patient_id"]: p for p in world.patients}
    appts = {a["appointment_id"]: a for a in world.appointments}
    completed = [a for a in world.appointments if a["status"] == "completed"]

    attended = Counter()
    no_show = Counter()
    for a in world.appointments:
        if a["status"] in ("completed", "no_show"):
            attended[a["location_id"]] += 1
            no_show[a["location_id"]] += a["status"] == "no_show"
    no_show_rows = sorted(([loc[l], str(pct(no_show[l], n))] for l, n in attended.items()),
                          key=lambda r: (-Decimal(r[1]), r[0]))

    lead = defaultdict(list)
    for a in world.appointments:
        if a["status"] != "cancelled":
            lead[a["service_id"]].append((a["starts_at"].date() - a["booked_at"].date()).days)
    lead_rows = sorted(([svc[s], str((Decimal(sum(d)) / len(d)).quantize(Decimal("0.1"), ROUND_HALF_UP))]
                        for s, d in lead.items()), key=lambda r: (-Decimal(r[1]), r[0]))

    june_done = {a["clinician_id"] for a in completed if a["starts_at"].month == 6}
    idle_rows = sorted([[doc[c]] for c in doc if c not in june_done])

    shift_min = Counter()
    for s in world.shifts:
        if s["shift_date"].month == 3:
            shift_min[s["clinician_id"]] += (s["ends_at"].hour - s["starts_at"].hour) * 60
    booked_min = Counter()
    for a in world.appointments:
        if a["starts_at"].month == 3 and a["status"] in ("completed", "no_show"):
            booked_min[a["clinician_id"]] += a["duration_min"]
    util_rows = sorted(([doc[c], str(pct(booked_min[c], m))] for c, m in shift_min.items()),
                       key=lambda r: (-Decimal(r[1]), r[0]))

    first_visit = {}
    for a in sorted(completed, key=lambda a: a["starts_at"]):
        first_visit.setdefault(a["patient_id"], a["starts_at"].month)
    new_by_month = Counter(first_visit.values())
    new_rows = [[m, new_by_month[m]] for m in range(1, 7)]

    paid = defaultdict(Decimal)
    for p in world.payments:
        paid[p["invoice_id"]] += p["amount"]
    owed = defaultdict(Decimal)
    for inv in world.invoices:
        payer = patients[appts[inv["appointment_id"]]["patient_id"]]["payer_type"]
        owed[payer] += inv["amount"] - paid[inv["invoice_id"]]
    owed_rows = sorted(([k, str(v)] for k, v in owed.items()), key=lambda r: (-Decimal(r[1]), r[0]))

    collected = defaultdict(Decimal)
    invoice_service = {inv["invoice_id"]: appts[inv["appointment_id"]]["service_id"] for inv in world.invoices}
    for p in world.payments:
        collected[svc[invoice_service[p["invoice_id"]]]] += p["amount"]
    collected_rows = sorted(([k, str(v)] for k, v in collected.items()), key=lambda r: (-Decimal(r[1]), r[0]))[:3]

    seen_by = defaultdict(set)
    for a in completed:
        seen_by[a["patient_id"]].add(a["clinician_id"])
    multi = sum(1 for s in seen_by.values() if len(s) > 1)

    return [
        {"id": "clinic_no_show_rate",
         "question": "What is the no-show rate at each clinic location?",
         "definition": "no-shows / (completed + no-show appointments) per location, percent to 1 decimal; cancelled appointments excluded",
         "columns": ["location", "no_show_rate_pct"], "rows": no_show_rows, "ordered": False,
         "reference_sql": """
            SELECT l.name AS location,
                   ROUND(100.0 * COUNT(*) FILTER (WHERE a.status = 'no_show') / COUNT(*), 1) AS no_show_rate_pct
            FROM appointments a JOIN locations l USING (location_id)
            WHERE a.status IN ('completed', 'no_show')
            GROUP BY l.name ORDER BY no_show_rate_pct DESC, location"""},
        {"id": "clinic_lead_time",
         "question": "What is the average booking lead time in days for each service?",
         "definition": "days from booked_at date to starts_at date, averaged over non-cancelled appointments per service, 1 decimal",
         "columns": ["service", "avg_lead_days"], "rows": lead_rows, "ordered": False,
         "reference_sql": """
            SELECT s.name AS service, ROUND(AVG(a.starts_at::date - a.booked_at::date), 1) AS avg_lead_days
            FROM appointments a JOIN services s USING (service_id)
            WHERE a.status <> 'cancelled'
            GROUP BY s.name ORDER BY avg_lead_days DESC, service"""},
        {"id": "clinic_idle_june",
         "question": "Which clinicians had no completed appointments in June 2025?",
         "definition": "clinicians with zero appointments of status completed starting in June 2025, including those with none at all",
         "columns": ["clinician"], "rows": idle_rows, "ordered": False,
         "reference_sql": """
            SELECT c.full_name AS clinician FROM clinicians c
            WHERE NOT EXISTS (SELECT 1 FROM appointments a WHERE a.clinician_id = c.clinician_id
                              AND a.status = 'completed'
                              AND a.starts_at >= '2025-06-01' AND a.starts_at < '2025-07-01')
            ORDER BY clinician"""},
        {"id": "clinic_utilization_march",
         "question": "What was each clinician's utilization in March 2025?",
         "definition": "minutes of completed and no-show appointments starting in March / minutes of that clinician's March shifts, percent to 1 decimal, for clinicians with March shifts",
         "columns": ["clinician", "utilization_pct"], "rows": util_rows, "ordered": False,
         "reference_sql": """
            WITH shift_minutes AS (
                SELECT clinician_id, SUM(EXTRACT(EPOCH FROM ends_at - starts_at) / 60) AS minutes
                FROM shifts WHERE shift_date >= '2025-03-01' AND shift_date < '2025-04-01'
                GROUP BY clinician_id),
            booked AS (
                SELECT clinician_id, SUM(duration_min) AS minutes FROM appointments
                WHERE status IN ('completed', 'no_show')
                  AND starts_at >= '2025-03-01' AND starts_at < '2025-04-01'
                GROUP BY clinician_id)
            SELECT c.full_name AS clinician,
                   ROUND(100.0 * COALESCE(b.minutes, 0) / s.minutes, 1) AS utilization_pct
            FROM shift_minutes s JOIN clinicians c USING (clinician_id)
            LEFT JOIN booked b USING (clinician_id)
            ORDER BY utilization_pct DESC, clinician"""},
        {"id": "clinic_new_patients",
         "question": "How many new patients did we see each month?",
         "definition": "a patient is new in the month of their first completed appointment; January to June 2025",
         "columns": ["month", "new_patients"], "rows": new_rows, "ordered": True,
         "reference_sql": """
            SELECT EXTRACT(MONTH FROM first_visit)::int AS month, COUNT(*) AS new_patients
            FROM (SELECT patient_id, MIN(starts_at) AS first_visit FROM appointments
                  WHERE status = 'completed' GROUP BY patient_id) f
            GROUP BY 1 ORDER BY 1"""},
        {"id": "clinic_outstanding_by_payer",
         "question": "What is the outstanding balance by payer type?",
         "definition": "invoice amount minus all payments on that invoice, summed by the patient's payer_type",
         "columns": ["payer_type", "outstanding"], "rows": owed_rows, "ordered": False,
         "reference_sql": """
            SELECT p.payer_type, SUM(i.amount - COALESCE(pp.paid, 0)) AS outstanding
            FROM invoices i
            JOIN appointments a USING (appointment_id)
            JOIN patients p USING (patient_id)
            LEFT JOIN (SELECT invoice_id, SUM(amount) AS paid FROM payments GROUP BY invoice_id) pp USING (invoice_id)
            GROUP BY p.payer_type ORDER BY outstanding DESC, p.payer_type"""},
        {"id": "clinic_top_services_collected",
         "question": "Which three services brought in the most money collected?",
         "definition": "sum of payments.amount by the service of the invoiced appointment, top 3",
         "columns": ["service", "collected"], "rows": collected_rows, "ordered": True,
         "reference_sql": """
            SELECT s.name AS service, SUM(py.amount) AS collected
            FROM payments py JOIN invoices i USING (invoice_id)
            JOIN appointments a USING (appointment_id) JOIN services s USING (service_id)
            GROUP BY s.name ORDER BY collected DESC, service LIMIT 3"""},
        {"id": "clinic_multi_clinician_patients",
         "question": "How many patients have been seen by more than one clinician?",
         "definition": "patients whose completed appointments involve at least two distinct clinicians",
         "columns": ["patients"], "rows": [[multi]], "ordered": True,
         "reference_sql": """
            SELECT COUNT(*) AS patients FROM (
                SELECT patient_id FROM appointments WHERE status = 'completed'
                GROUP BY patient_id HAVING COUNT(DISTINCT clinician_id) > 1) m"""},
    ]


def summary(world: World) -> dict:
    return {table: len(getattr(world, table)) for table in COLUMNS}


if __name__ == "__main__":
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
