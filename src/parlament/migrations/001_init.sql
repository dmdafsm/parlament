-- Initial schema. Full-text search uses the 'simple' configuration on unaccented text with prefix queries
-- (see analytics.ts_query): people search without diacritics, which the Romanian stemmer does not handle.
-- Every row keeps its source page (`url`) so the site can link back to the official record.
-- Chambers: 'cd' = Camera Deputaților (cdep.ro cam=2), 'senat' = Senatul (cdep.ro cam=1 / senat.ro).

CREATE EXTENSION IF NOT EXISTS unaccent;

-- unaccent() is not IMMUTABLE, so wrap it for use in generated columns and indexes.
CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;

CREATE TABLE ingest_log (
    id          serial PRIMARY KEY,
    source      text NOT NULL,
    command     text NOT NULL,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status      text NOT NULL DEFAULT 'running',
    rows        integer,
    error       text
);

CREATE TABLE parl_groups (
    id          text PRIMARY KEY,               -- '<chamber>-<leg>-<source id>'
    chamber     text NOT NULL,
    legislature integer NOT NULL,
    source_id   text NOT NULL,
    short_name  text,
    name        text NOT NULL,
    url         text
);

CREATE TABLE members (
    id                text PRIMARY KEY,         -- 'cd-2024-133', 'senat-2024-<guid>'
    chamber           text NOT NULL CHECK (chamber IN ('cd', 'senat')),
    legislature       integer NOT NULL,
    source            text NOT NULL,            -- 'cdep.ro' or 'senat.ro'
    source_id         text NOT NULL,
    name              text NOT NULL,            -- display order: first names then surname
    sort_name         text NOT NULL,            -- surname first, as listed by the chamber
    birth_date        date,
    photo_url         text,
    url               text NOT NULL,
    constituency_no   integer,                  -- 1-41 counties, 42 București, 43 Diaspora; NULL for minorities/national
    constituency      text,
    elected_note      text,
    group_id          text REFERENCES parl_groups (id),
    party             text,                     -- current party short name as published
    party_name        text,
    minority_org      text,
    validated_on      date,
    mandate_end       date,                     -- set when the mandate ended early
    mandate_end_note  text,
    offices           text,                     -- constituency office addresses, as published
    email             text,
    phone             text,
    bio               text,
    in_office         boolean NOT NULL DEFAULT true,
    updated_at        timestamptz NOT NULL DEFAULT now(),
    search            tsvector GENERATED ALWAYS AS (to_tsvector('simple', f_unaccent(coalesce(name, '')))) STORED
);
CREATE INDEX members_chamber_idx ON members (chamber, legislature);
CREATE INDEX members_search_idx ON members USING gin (search);

-- Group and party history. cdep.ro publishes changes with month precision ('sep. 2023'),
-- stored as the first day of the month with precision = 'month'.
CREATE TABLE group_memberships (
    member_id   text NOT NULL REFERENCES members (id) ON DELETE CASCADE,
    seq         integer NOT NULL,
    group_id    text REFERENCES parl_groups (id),
    group_name  text NOT NULL,
    start_date  date,
    end_date    date,
    precision   text NOT NULL DEFAULT 'month',
    PRIMARY KEY (member_id, seq)
);

CREATE TABLE party_memberships (
    member_id   text NOT NULL REFERENCES members (id) ON DELETE CASCADE,
    seq         integer NOT NULL,
    party       text NOT NULL,                  -- short name, or the published label for 'no party'
    party_name  text,
    start_date  date,
    end_date    date,
    precision   text NOT NULL DEFAULT 'month',
    PRIMARY KEY (member_id, seq)
);

CREATE TABLE group_roles (
    member_id   text NOT NULL REFERENCES members (id) ON DELETE CASCADE,
    seq         integer NOT NULL,
    group_name  text NOT NULL,
    role        text NOT NULL,                  -- 'Lider', 'Vicelider', 'Secretar'
    start_date  date,
    end_date    date,
    PRIMARY KEY (member_id, seq)
);

CREATE TABLE committees (
    id          text PRIMARY KEY,
    chamber     text NOT NULL,
    legislature integer NOT NULL,
    name        text NOT NULL,
    url         text
);

CREATE TABLE committee_memberships (
    member_id    text NOT NULL REFERENCES members (id) ON DELETE CASCADE,
    committee_id text NOT NULL REFERENCES committees (id),
    role         text,
    start_date   date,
    PRIMARY KEY (member_id, committee_id)
);

-- Activity counters exactly as the chamber publishes them on the profile page.
CREATE TABLE member_stats (
    member_id   text NOT NULL REFERENCES members (id) ON DELETE CASCADE,
    metric      text NOT NULL,                  -- speeches, speech_sessions, bills, laws, motions, questions, interpellations, political_statements, vote_sessions, vote_sessions_total
    value       integer NOT NULL,
    url         text,
    collected_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (member_id, metric)
);

CREATE TABLE bills (
    id                 text PRIMARY KEY,        -- 'cd-<idp>'
    source_id          text NOT NULL,
    number             text,                    -- 'PL-x 164/2024'
    cd_number          text,                    -- '164/18.03.2024'
    senate_number      text,                    -- 'L748/2023'
    senate_url         text,
    bpi_number         text,
    title              text NOT NULL,
    kind               text,                    -- 'Proiect de Lege', 'Propunere legislativă', ...
    procedure          text,
    decisional_chamber text,
    character          text,                    -- ordinar / organic
    urgent             boolean,
    status             text,
    law                text,                    -- 'Lege 234/2024' when promulgated
    law_url            text,
    initiator_summary  text,
    registered_on      date,
    last_event_on      date,
    ordinance          text,                    -- 'OUG 224/2020' when the bill approves an emergency ordinance
    url                text NOT NULL,
    updated_at         timestamptz NOT NULL DEFAULT now(),
    search             tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', f_unaccent(coalesce(number, '') || ' ' || coalesce(senate_number, ''))), 'A')
        || setweight(to_tsvector('simple', f_unaccent(coalesce(title, ''))), 'B')
    ) STORED
);
CREATE INDEX bills_search_idx ON bills USING gin (search);
CREATE INDEX bills_last_event_idx ON bills (last_event_on DESC NULLS LAST);

CREATE TABLE bill_initiators (
    bill_id    text NOT NULL REFERENCES bills (id) ON DELETE CASCADE,
    seq        integer NOT NULL,
    member_ref text,                            -- '<chamber>-<leg>-<idm>' as linked; may point to an earlier legislature
    name       text NOT NULL,
    label      text,                            -- 'deputati - PNL', 'Guvern'
    PRIMARY KEY (bill_id, seq)
);
CREATE INDEX bill_initiators_member_idx ON bill_initiators (member_ref);

CREATE TABLE bill_events (
    bill_id    text NOT NULL REFERENCES bills (id) ON DELETE CASCADE,
    seq        integer NOT NULL,
    event_date date,
    chamber    text,
    action     text NOT NULL,
    notes      text,
    documents  jsonb NOT NULL DEFAULT '[]',
    PRIMARY KEY (bill_id, seq)
);

CREATE TABLE bill_documents (
    bill_id text NOT NULL REFERENCES bills (id) ON DELETE CASCADE,
    seq     integer NOT NULL,
    title   text NOT NULL,
    url     text NOT NULL,
    PRIMARY KEY (bill_id, seq)
);

CREATE TABLE votes (
    id          text PRIMARY KEY,               -- 'cd-<idv>'
    chamber     text NOT NULL,
    source_id   text NOT NULL,
    voted_at    timestamp NOT NULL,             -- local Bucharest time, as published
    description text NOT NULL,
    bill_ref    text,                           -- 'PL-x 548/2022' found in the description
    bill_id     text REFERENCES bills (id),
    present     integer,
    yes         integer,
    no          integer,
    abstain     integer,
    not_voted   integer,
    is_test     boolean NOT NULL DEFAULT false,
    has_nominal boolean NOT NULL DEFAULT false,
    url         text NOT NULL,
    search      tsvector GENERATED ALWAYS AS (to_tsvector('simple', f_unaccent(coalesce(description, '')))) STORED
);
CREATE INDEX votes_time_idx ON votes (voted_at DESC);
CREATE INDEX votes_bill_idx ON votes (bill_id);
CREATE INDEX votes_search_idx ON votes USING gin (search);

-- One row per MP present at the vote. MPs who were not present are not listed by the source;
-- absence is derived from the mandate dates (see analytics.py), never stored as a vote.
CREATE TABLE vote_records (
    vote_id    text NOT NULL REFERENCES votes (id) ON DELETE CASCADE,
    member_id  text NOT NULL,
    member_name text,                           -- as printed on the vote (the member may be from another legislature)
    group_code text,                            -- group as printed on the vote ('PSD', 'Neafiliati')
    choice     text NOT NULL CHECK (choice IN ('yes', 'no', 'abstain', 'present_not_voting')),
    PRIMARY KEY (vote_id, member_id)
);
CREATE INDEX vote_records_member_idx ON vote_records (member_id);

CREATE TABLE questions (
    id          text PRIMARY KEY,               -- 'cd-<idi>'
    member_id   text NOT NULL REFERENCES members (id) ON DELETE CASCADE,
    kind        text NOT NULL,                  -- 'intrebare', 'interpelare'
    number      text,
    asked_on    date,
    title       text,
    recipient   text,
    answered    boolean,
    url         text NOT NULL
);
CREATE INDEX questions_member_idx ON questions (member_id);

CREATE TABLE speeches (
    member_id   text NOT NULL REFERENCES members (id) ON DELETE CASCADE,
    seq         integer NOT NULL,
    sitting     text NOT NULL,                  -- 'Ședința Camerei Deputaților din 19 iunie 2007'
    sitting_on  date,
    topic       text,
    duration    text,
    url         text,
    PRIMARY KEY (member_id, seq),
    search      tsvector GENERATED ALWAYS AS (to_tsvector('simple', f_unaccent(coalesce(topic, '')))) STORED
);
CREATE INDEX speeches_search_idx ON speeches USING gin (search);

CREATE TABLE motions (
    id          text PRIMARY KEY,
    chamber     text NOT NULL,
    title       text NOT NULL,
    initiators  text,
    registered  text,
    result      text,
    url         text NOT NULL
);

CREATE TABLE motion_signatures (
    motion_id text NOT NULL REFERENCES motions (id) ON DELETE CASCADE,
    member_id text NOT NULL REFERENCES members (id) ON DELETE CASCADE,
    PRIMARY KEY (motion_id, member_id)
);

CREATE TABLE agendas (
    id          text PRIMARY KEY,               -- 'cd-<oid>'
    chamber     text NOT NULL,
    title       text NOT NULL,
    approved_on date,
    first_day   date,
    pdf_url     text,
    url         text NOT NULL
);

CREATE TABLE agenda_items (
    agenda_id  text NOT NULL REFERENCES agendas (id) ON DELETE CASCADE,
    seq        integer NOT NULL,
    position   text,
    bill_ref   text,
    bill_id    text REFERENCES bills (id),
    text       text NOT NULL,
    PRIMARY KEY (agenda_id, seq)
);

CREATE TABLE declarations (
    member_id  text NOT NULL REFERENCES members (id) ON DELETE CASCADE,
    kind       text NOT NULL,                   -- 'avere', 'interese'
    filed_on   date,
    url        text NOT NULL,
    PRIMARY KEY (member_id, kind, url)
);
