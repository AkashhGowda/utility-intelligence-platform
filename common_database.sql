--
-- PostgreSQL database dump
--

\restrict 0Eq4RKaczXwZPBGBm4dXNQS6clOR7Cu0Ua1UpXLvKoqtxiins4fN5ejAyoQeRrV

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

COPY common.location (location_id, location_name) FROM stdin;
1	Bangalore
\.


--
-- TOC entry 5020 (class 0 OID 16392)
-- Dependencies: 221
-- Data for Name: plant; Type: TABLE DATA; Schema: common; Owner: postgres
--

COPY common.plant (plant_id, plant_name, location_id) FROM stdin;
1	TPREL	1
\.


--
-- TOC entry 5021 (class 0 OID 16403)
-- Dependencies: 222
-- Data for Name: production_line; Type: TABLE DATA; Schema: common; Owner: postgres
--

COPY common.production_line (production_line_id, production_line_name, plant_id) FROM stdin;
1	Vega	1
2	Galaxy	1
3	Hexa	1
\.


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

\unrestrict 0Eq4RKaczXwZPBGBm4dXNQS6clOR7Cu0Ua1UpXLvKoqtxiins4fN5ejAyoQeRrV

