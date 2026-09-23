--
-- PostgreSQL database dump
--

-- Dumped from database version 18.6
-- Dumped by pg_dump version 18.6

-- Started on 2026-09-10 12:11:30

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- TOC entry 6 (class 2615 OID 16385)
-- Name: common; Type: SCHEMA; Schema: -; Owner: postgres
--

CREATE SCHEMA common;


ALTER SCHEMA common OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- TOC entry 220 (class 1259 OID 16386)
-- Name: location; Type: TABLE; Schema: common; Owner: postgres
--

CREATE TABLE common.location (
    location_id integer NOT NULL,
    location_name character varying(100)
);


ALTER TABLE common.location OWNER TO postgres;

--
-- TOC entry 221 (class 1259 OID 16392)
-- Name: plant; Type: TABLE; Schema: common; Owner: postgres
--

CREATE TABLE common.plant (
    plant_id integer NOT NULL,
    plant_name character varying(100),
    location_id integer
);


ALTER TABLE common.plant OWNER TO postgres;

--
-- TOC entry 222 (class 1259 OID 16403)
-- Name: production_line; Type: TABLE; Schema: common; Owner: postgres
--

CREATE TABLE common.production_line (
    production_line_id integer NOT NULL,
    production_line_name character varying(100),
    plant_id integer
);


ALTER TABLE common.production_line OWNER TO postgres;

--
-- TOC entry 5019 (class 0 OID 16386)
-- Dependencies: 220
-- Data for Name: location; Type: TABLE DATA; Schema: common; Owner: postgres
--

INSERT INTO common.location (location_id, location_name)
VALUES (1, 'Bangalore');


--
-- TOC entry 5020 (class 0 OID 16392)
-- Dependencies: 221
-- Data for Name: plant; Type: TABLE DATA; Schema: common; Owner: postgres
--

INSERT INTO common.plant (plant_id, plant_name, location_id)
VALUES (1, 'TPREL', 1);


--
-- TOC entry 5021 (class 0 OID 16403)
-- Dependencies: 222
-- Data for Name: production_line; Type: TABLE DATA; Schema: common; Owner: postgres
--

INSERT INTO common.production_line (production_line_id, production_line_name, plant_id)
VALUES
    (1, 'Vega', 1),
    (2, 'Galaxy', 1),
    (3, 'Hexa', 1);


--
-- TOC entry 4865 (class 2606 OID 16391)
-- Name: location pk_location; Type: CONSTRAINT; Schema: common; Owner: postgres
--

ALTER TABLE ONLY common.location
    ADD CONSTRAINT pk_location PRIMARY KEY (location_id);


--
-- TOC entry 4867 (class 2606 OID 16397)
-- Name: plant pk_plant; Type: CONSTRAINT; Schema: common; Owner: postgres
--

ALTER TABLE ONLY common.plant
    ADD CONSTRAINT pk_plant PRIMARY KEY (plant_id);


--
-- TOC entry 4869 (class 2606 OID 16408)
-- Name: production_line pk_production_line; Type: CONSTRAINT; Schema: common; Owner: postgres
--

ALTER TABLE ONLY common.production_line
    ADD CONSTRAINT pk_production_line PRIMARY KEY (production_line_id);


--
-- TOC entry 4870 (class 2606 OID 16398)
-- Name: plant fk_plant_location; Type: FK CONSTRAINT; Schema: common; Owner: postgres
--

ALTER TABLE ONLY common.plant
    ADD CONSTRAINT fk_plant_location FOREIGN KEY (location_id) REFERENCES common.location(location_id);


--
-- TOC entry 4871 (class 2606 OID 16409)
-- Name: production_line fk_production_line_plant; Type: FK CONSTRAINT; Schema: common; Owner: postgres
--

ALTER TABLE ONLY common.production_line
    ADD CONSTRAINT fk_production_line_plant FOREIGN KEY (plant_id) REFERENCES common.plant(plant_id);


-- Completed on 2026-09-10 12:11:30

--
-- PostgreSQL database dump complete
--


-- Application schema required by the current login and admin services.
SET search_path = public;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS platform;

CREATE TABLE IF NOT EXISTS platform.plants (
    plant_id SERIAL PRIMARY KEY,
    plant_name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS platform.locations (
    location_id SERIAL PRIMARY KEY,
    location_code TEXT NOT NULL UNIQUE,
    location_name TEXT NOT NULL UNIQUE,
    plant_id INTEGER NOT NULL REFERENCES platform.plants(plant_id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS platform.user_types (
    user_type_id SERIAL PRIMARY KEY,
    type_code TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS platform.applications (
    application_id SERIAL PRIMARY KEY,
    application_code TEXT NOT NULL UNIQUE,
    application_name TEXT NOT NULL,
    base_route TEXT NOT NULL DEFAULT '/',
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS platform.users (
    user_id SERIAL PRIMARY KEY,
    employee_id TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    user_type_id INTEGER NOT NULL REFERENCES platform.user_types(user_type_id),
    plant_id INTEGER NOT NULL REFERENCES platform.plants(plant_id),
    location_id INTEGER NOT NULL REFERENCES platform.locations(location_id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS platform.user_applications (
    user_id INTEGER NOT NULL REFERENCES platform.users(user_id) ON DELETE CASCADE,
    application_id INTEGER NOT NULL REFERENCES platform.applications(application_id) ON DELETE CASCADE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (user_id, application_id)
);

INSERT INTO platform.plants (plant_name)
VALUES ('TATA POWER SOLAR UNIT-1'), ('TATA POWER SOLAR UNIT-2')
ON CONFLICT (plant_name) DO NOTHING;
INSERT INTO platform.locations (location_code, location_name, plant_id)
SELECT 'TATA-SOLAR-UNIT-1',
       '78, Hosur Rd, Suryanagar Phase I, Electronic City, Doddathoguru, Karnataka 560100',
       plant_id
FROM platform.plants
WHERE plant_name = 'TATA POWER SOLAR UNIT-1'
ON CONFLICT (location_code) DO NOTHING;
INSERT INTO platform.locations (location_code, location_name, plant_id)
SELECT 'TATA-SOLAR-UNIT-2',
       'Electronic City Rd, Phase II, Electronic City, Konappana Agrahara, Karnataka 560100',
       plant_id
FROM platform.plants
WHERE plant_name = 'TATA POWER SOLAR UNIT-2'
ON CONFLICT (location_code) DO NOTHING;
INSERT INTO platform.user_types (type_code) VALUES ('ADMIN'), ('ANALYST')
ON CONFLICT (type_code) DO NOTHING;
INSERT INTO platform.applications (application_code, application_name, base_route)
VALUES ('ADMIN', 'Admin Control Center', '/admin'),
       ('UTILITY', 'Utility', '/utility'),
       ('SIMULATION', 'Simulation', '/simulation'),
       ('EL_DATA', 'EL Data', '/el-data')
ON CONFLICT (application_code) DO NOTHING;

INSERT INTO platform.users
    (employee_id, username, full_name, email, password_hash, user_type_id, plant_id, location_id)
SELECT 'DEMO-ADMIN', 'admin', 'Demo Administrator', 'admin@localhost',
       crypt('admin', gen_salt('bf')), ut.user_type_id, p.plant_id, l.location_id
FROM platform.user_types ut, platform.plants p, platform.locations l
WHERE ut.type_code = 'ADMIN' AND p.plant_name = 'TATA POWER SOLAR UNIT-1'
    AND l.location_name = '78, Hosur Rd, Suryanagar Phase I, Electronic City, Doddathoguru, Karnataka 560100'
ON CONFLICT (username) DO NOTHING;
INSERT INTO platform.users
    (employee_id, username, full_name, email, password_hash, user_type_id, plant_id, location_id)
SELECT 'DEMO-USER', 'demo', 'Demo User', 'demo@localhost',
       crypt('demo', gen_salt('bf')), ut.user_type_id, p.plant_id, l.location_id
FROM platform.user_types ut, platform.plants p, platform.locations l
WHERE ut.type_code = 'ANALYST' AND p.plant_name = 'TATA POWER SOLAR UNIT-1'
    AND l.location_name = '78, Hosur Rd, Suryanagar Phase I, Electronic City, Doddathoguru, Karnataka 560100'
ON CONFLICT (username) DO NOTHING;
INSERT INTO platform.user_applications (user_id, application_id, is_default)
SELECT u.user_id, a.application_id, TRUE FROM platform.users u, platform.applications a
WHERE u.username = 'admin' AND a.application_code = 'ADMIN' ON CONFLICT DO NOTHING;
INSERT INTO platform.user_applications (user_id, application_id, is_default)
SELECT u.user_id, a.application_id, TRUE FROM platform.users u, platform.applications a
WHERE u.username = 'demo' AND a.application_code = 'UTILITY' ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.solar_locations (
    location_id INTEGER PRIMARY KEY,
    location_name TEXT NOT NULL UNIQUE,
    site_location TEXT DEFAULT '78, Hosur Rd, Suryanagar Phase I, Electronic City, Doddathoguru, Karnataka 560100',
    plant_name TEXT DEFAULT 'TATA POWER SOLAR UNIT-1',
    line_name TEXT DEFAULT 'Vega',
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT DEFAULT 'system',
    modified_by TEXT DEFAULT 'system'
);
CREATE TABLE IF NOT EXISTS public.solar_daily_summary (
    summary_id SERIAL PRIMARY KEY,
    location_id INTEGER NOT NULL REFERENCES public.solar_locations(location_id),
    log_date TEXT NOT NULL,
    generation_kwh REAL NOT NULL,
    site_location TEXT DEFAULT '78, Hosur Rd, Suryanagar Phase I, Electronic City, Doddathoguru, Karnataka 560100',
    plant_name TEXT DEFAULT 'TATA POWER SOLAR UNIT-1',
    line_name TEXT DEFAULT 'Vega',
    UNIQUE (location_id, log_date)
);
CREATE TABLE IF NOT EXISTS public.solar_time_logs (
    log_id SERIAL PRIMARY KEY,
    location_id INTEGER NOT NULL REFERENCES public.solar_locations(location_id),
    log_date TEXT NOT NULL,
    log_timestamp TEXT NOT NULL,
    kwh REAL, kvah REAL, kw REAL, kva REAL, current REAL, power_factor REAL,
    site_location TEXT DEFAULT '78, Hosur Rd, Suryanagar Phase I, Electronic City, Doddathoguru, Karnataka 560100',
    plant_name TEXT DEFAULT 'TATA POWER SOLAR UNIT-1',
    line_name TEXT DEFAULT 'Vega',
    UNIQUE (location_id, log_date, log_timestamp)
);

ALTER TABLE public.solar_locations
    ALTER COLUMN site_location SET DEFAULT '78, Hosur Rd, Suryanagar Phase I, Electronic City, Doddathoguru, Karnataka 560100',
    ALTER COLUMN plant_name SET DEFAULT 'TATA POWER SOLAR UNIT-1';
ALTER TABLE public.solar_daily_summary
    ALTER COLUMN site_location SET DEFAULT '78, Hosur Rd, Suryanagar Phase I, Electronic City, Doddathoguru, Karnataka 560100',
    ALTER COLUMN plant_name SET DEFAULT 'TATA POWER SOLAR UNIT-1';
ALTER TABLE public.solar_time_logs
    ALTER COLUMN site_location SET DEFAULT '78, Hosur Rd, Suryanagar Phase I, Electronic City, Doddathoguru, Karnataka 560100',
    ALTER COLUMN plant_name SET DEFAULT 'TATA POWER SOLAR UNIT-1';

CREATE TABLE IF NOT EXISTS platform.utilities (
    utility_id SERIAL PRIMARY KEY,
    utility_code TEXT NOT NULL UNIQUE,
    utility_name TEXT NOT NULL,
    utility_type TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'unit',
    plant_id INTEGER NOT NULL REFERENCES platform.plants(plant_id),
    location_id INTEGER NOT NULL REFERENCES platform.locations(location_id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

