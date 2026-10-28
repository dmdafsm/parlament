-- Stenograms now come from both chambers: cdep.ro HTML pages and senat.ro PDFs (one per sitting).
ALTER TABLE stenograms ADD COLUMN chamber text NOT NULL DEFAULT 'cd' CHECK (chamber IN ('cd', 'senat'));
