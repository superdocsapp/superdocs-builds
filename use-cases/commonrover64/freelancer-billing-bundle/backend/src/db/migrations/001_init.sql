CREATE TABLE IF NOT EXISTS clients (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT,
  phone TEXT,
  address TEXT
);

-- New row = rate change. Old rows stay untouched, so past invoices still reconcile.
CREATE TABLE IF NOT EXISTS rate_cards (
  id SERIAL PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id),
  hourly_rate NUMERIC NOT NULL,
  currency TEXT NOT NULL DEFAULT 'INR',
  effective_from DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS engagements (
  id SERIAL PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id),
  title TEXT NOT NULL,
  start_date DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS timesheet_entries (
  id SERIAL PRIMARY KEY,
  engagement_id INTEGER NOT NULL REFERENCES engagements(id),
  entry_date DATE NOT NULL,
  hours NUMERIC NOT NULL,
  description TEXT
);