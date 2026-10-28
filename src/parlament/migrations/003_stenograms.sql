-- Stenogram text from cdep.ro, one row per speaker turn, for full-text search of what was said in plenary.

-- One stenogram page per agenda point of a sitting (steno2015.stenograma?ids=<sitting>&idm=<point>).
CREATE TABLE stenograms (
    url        text PRIMARY KEY,
    sitting    text,                           -- 'Ședința Camerei Deputaților din 5 noiembrie 2025'
    sitting_on date,
    title      text,                           -- the agenda point
    fetched_at timestamptz NOT NULL DEFAULT now()
);

-- A turn is everything one speaker said until the next speaker; interjections stay in the turn as printed.
-- member_id is set when the speaker's name links to an MP profile we have (ministers and guests have none).
CREATE TABLE speech_texts (
    url       text NOT NULL REFERENCES stenograms (url) ON DELETE CASCADE,
    seq       integer NOT NULL,
    member_id text REFERENCES members (id) ON DELETE SET NULL,
    speaker   text NOT NULL,
    body      text NOT NULL,
    PRIMARY KEY (url, seq),
    search    tsvector GENERATED ALWAYS AS (to_tsvector('simple', f_unaccent(body))) STORED
);
CREATE INDEX speech_texts_search_idx ON speech_texts USING gin (search);
CREATE INDEX speech_texts_member_idx ON speech_texts (member_id);
