DROP TABLE IF EXISTS substitution_requests;
DROP TABLE IF EXISTS duty_roster;
DROP TABLE IF EXISTS worship_services;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS churches;

CREATE TABLE churches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    scheduling_rules TEXT
);

CREATE TABLE worship_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    church_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    time TEXT NOT NULL,
    activities TEXT NOT NULL,
    FOREIGN KEY(church_id) REFERENCES churches(id)
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL,
    church_id INTEGER,
    FOREIGN KEY(church_id) REFERENCES churches(id)
);

CREATE TABLE duty_roster (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    church_id INTEGER,
    duty_date TEXT,
    activity TEXT,
    user_id INTEGER,
    FOREIGN KEY(church_id) REFERENCES churches(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE substitution_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    duty_id INTEGER,
    requester_id INTEGER,
    requested_substitute_id INTEGER,
    status TEXT,
    message TEXT,
    FOREIGN KEY(duty_id) REFERENCES duty_roster(id),
    FOREIGN KEY(requester_id) REFERENCES users(id),
    FOREIGN KEY(requested_substitute_id) REFERENCES users(id)
);
