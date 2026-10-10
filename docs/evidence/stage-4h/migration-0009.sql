BEGIN;

CREATE TABLE jarvis_schema_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT jarvis_schema_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_foundation

CREATE SCHEMA app;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
GRANT USAGE ON SCHEMA app TO jarvis_app;

CREATE FUNCTION app.current_owner_id() RETURNS uuid
LANGUAGE sql STABLE SET search_path = pg_catalog
AS $$ SELECT NULLIF(current_setting('jarvis.owner_id', true), '')::uuid $$;
REVOKE ALL ON FUNCTION app.current_owner_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.current_owner_id() TO jarvis_app;

CREATE TABLE app.users (
  id uuid PRIMARY KEY,
  display_name varchar(100) NOT NULL,
  timezone varchar(64) NOT NULL,
  status varchar(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE app.api_tokens (
  id uuid PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES app.users(id),
  secret_digest bytea NOT NULL CHECK (octet_length(secret_digest)=32),
  label varchar(80) NOT NULL,
  scopes text[] NOT NULL CHECK (cardinality(scopes)>0),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  last_used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_api_tokens_owner_id ON app.api_tokens(owner_id);
CREATE INDEX ix_api_tokens_expires_at ON app.api_tokens(expires_at);

CREATE TABLE app.pairing_codes (
  id uuid PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES app.users(id),
  secret_digest bytea NOT NULL CHECK (octet_length(secret_digest)=32),
  expected_sender_id bigint NOT NULL CHECK (expected_sender_id>0),
  expires_at timestamptz NOT NULL,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts>=0 AND attempts<=5),
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_pairing_codes_owner_id ON app.pairing_codes(owner_id);

CREATE TABLE app.external_identities (
  id uuid PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES app.users(id),
  channel varchar(32) NOT NULL CHECK (channel='telegram'),
  external_user_id bigint NOT NULL CHECK (external_user_id>0),
  chat_id bigint NOT NULL CHECK (chat_id=external_user_id),
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT identity_channel_user UNIQUE(channel,external_user_id),
  CONSTRAINT identity_owner_channel UNIQUE(owner_id,channel)
);
CREATE INDEX ix_external_identities_owner_id ON app.external_identities(owner_id);

CREATE TABLE app.audit_events (
  id uuid PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES app.users(id),
  actor_id uuid,
  action varchar(64) NOT NULL,
  resource_id uuid,
  metadata_safe jsonb NOT NULL DEFAULT '{}',
  request_id varchar(36),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_events_owner_id ON app.audit_events(owner_id,created_at DESC);

REVOKE ALL ON ALL TABLES IN SCHEMA app FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON app.users,app.api_tokens,app.pairing_codes,
  app.external_identities TO jarvis_app;
GRANT SELECT,INSERT ON app.audit_events TO jarvis_app;
GRANT SELECT ON public.jarvis_schema_version TO jarvis_app;;

ALTER TABLE app.users ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.users FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.users USING (id = app.current_owner_id()) WITH CHECK (id = app.current_owner_id());

ALTER TABLE app.api_tokens ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.api_tokens FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.api_tokens USING (owner_id = app.current_owner_id()) WITH CHECK (owner_id = app.current_owner_id());

ALTER TABLE app.pairing_codes ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.pairing_codes FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.pairing_codes USING (owner_id = app.current_owner_id()) WITH CHECK (owner_id = app.current_owner_id());

ALTER TABLE app.external_identities ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.external_identities FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.external_identities USING (owner_id = app.current_owner_id()) WITH CHECK (owner_id = app.current_owner_id());

ALTER TABLE app.audit_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.audit_events FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.audit_events USING (owner_id = app.current_owner_id()) WITH CHECK (owner_id = app.current_owner_id());

INSERT INTO jarvis_schema_version (version_num) VALUES ('0001_foundation') RETURNING jarvis_schema_version.version_num;

-- Running upgrade 0001_foundation -> 0002_telegram

CREATE TABLE app.telegram_state (
  owner_id uuid PRIMARY KEY REFERENCES app.users(id),
  bot_id bigint NOT NULL CHECK (bot_id>0),
  next_offset bigint CHECK (next_offset>=0),
  last_update_at timestamptz,
  last_poll_at timestamptz,
  send_not_before timestamptz,
  rate_window_at timestamptz NOT NULL,
  rate_count integer NOT NULL DEFAULT 0 CHECK (rate_count BETWEEN 0 AND 20),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT telegram_bot_owner UNIQUE(bot_id),
  CONSTRAINT telegram_owner_bot UNIQUE(owner_id,bot_id)
);
CREATE TABLE app.telegram_receipts (
  owner_id uuid NOT NULL,
  bot_id bigint NOT NULL,
  update_id bigint NOT NULL CHECK (update_id>=0),
  chat_id bigint NOT NULL CHECK (chat_id>0),
  reply_kind varchar(32) CHECK (reply_kind IN
    ('unpaired','paired','pair_failed','already_paired','help','status','privacy','unsupported')),
  requires_pairing boolean NOT NULL DEFAULT true,
  delivery_status varchar(16) NOT NULL CHECK (delivery_status IN
    ('pending','sending','sent','uncertain','failed','blocked','ignored','expired')),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
  next_attempt_at timestamptz NOT NULL,
  telegram_message_id bigint,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(owner_id,bot_id,update_id),
  FOREIGN KEY(owner_id,bot_id) REFERENCES app.telegram_state(owner_id,bot_id)
);
CREATE INDEX ix_telegram_delivery ON app.telegram_receipts(owner_id,bot_id,next_attempt_at)
  WHERE delivery_status='pending';
CREATE INDEX ix_telegram_retention ON app.telegram_receipts(owner_id,bot_id,created_at);
REVOKE ALL ON app.telegram_state, app.telegram_receipts FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON app.telegram_state TO jarvis_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON app.telegram_receipts TO jarvis_app;;

ALTER TABLE app.telegram_state ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.telegram_state FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.telegram_state USING (owner_id = app.current_owner_id()) WITH CHECK (owner_id = app.current_owner_id());

ALTER TABLE app.telegram_receipts ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.telegram_receipts FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.telegram_receipts USING (owner_id = app.current_owner_id()) WITH CHECK (owner_id = app.current_owner_id());

UPDATE jarvis_schema_version SET version_num='0002_telegram' WHERE jarvis_schema_version.version_num = '0001_foundation';

-- Running upgrade 0002_telegram -> 0003_assistant

ALTER TABLE app.telegram_receipts ADD COLUMN reply_text text
  CHECK (octet_length(reply_text)<=16000);
ALTER TABLE app.telegram_receipts DROP CONSTRAINT telegram_receipts_reply_kind_check;
ALTER TABLE app.telegram_receipts ADD CONSTRAINT telegram_receipts_reply_kind_check
 CHECK (reply_kind IN ('unpaired','paired','pair_failed','already_paired','help','status',
 'privacy','unsupported','assistant'));
ALTER TABLE app.telegram_receipts DROP CONSTRAINT telegram_receipts_delivery_status_check;
ALTER TABLE app.telegram_receipts ADD CONSTRAINT telegram_receipts_delivery_status_check
 CHECK (delivery_status IN ('pending','sending','sent','uncertain','failed','blocked',
 'ignored','expired','waiting'));
CREATE TABLE app.assistant_state (
 owner_id uuid PRIMARY KEY REFERENCES app.users(id),
 enabled boolean NOT NULL DEFAULT false,
 frozen boolean NOT NULL DEFAULT false,
 revision integer NOT NULL DEFAULT 1 CHECK (revision>0),
 conversation_id uuid NOT NULL,
 config_hash varchar(64) NOT NULL,
 last_poll_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE app.profile_memory (
 owner_id uuid NOT NULL REFERENCES app.users(id),
 key varchar(40) NOT NULL,
 value text NOT NULL CHECK (octet_length(value)<=4000),
 data_class varchar(16) NOT NULL DEFAULT 'private' CHECK (data_class IN ('private','restricted')),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (owner_id,key)
);
CREATE TABLE app.assistant_requests (
 id uuid PRIMARY KEY,
 owner_id uuid NOT NULL REFERENCES app.users(id),
 bot_id bigint NOT NULL,
 source_update_id bigint NOT NULL,
 reply_update_id bigint NOT NULL,
 conversation_id uuid NOT NULL,
 revision integer NOT NULL,
 config_hash varchar(64) NOT NULL,
 prompt text CHECK (octet_length(prompt)<=16000),
 messages jsonb,
 context_hash varchar(64),
 data_class varchar(16) NOT NULL DEFAULT 'private' CHECK (data_class IN ('private','restricted')),
 status varchar(24) NOT NULL CHECK (status IN ('queued','preparing','awaiting_approval',
  'approved','dispatching','succeeded','failed','uncertain','cancelled')),
 plan jsonb,
 approval_digest bytea CHECK (octet_length(approval_digest)=32),
 approval_expires_at timestamptz,
 approved_at timestamptz,
 consumed_at timestamptz,
 approval_attempts integer NOT NULL DEFAULT 0 CHECK (approval_attempts BETWEEN 0 AND 5),
 created_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz,
 UNIQUE(owner_id,id), UNIQUE(owner_id,bot_id,source_update_id),
 FOREIGN KEY(owner_id,bot_id) REFERENCES app.telegram_state(owner_id,bot_id)
);
CREATE UNIQUE INDEX ix_one_assistant_request ON app.assistant_requests(owner_id)
 WHERE status IN ('queued','preparing','awaiting_approval','approved','dispatching');
CREATE INDEX ix_assistant_request_retention ON app.assistant_requests(owner_id,created_at);
CREATE TABLE app.conversation_messages (
 id uuid PRIMARY KEY,
 owner_id uuid NOT NULL REFERENCES app.users(id),
 conversation_id uuid NOT NULL,
 request_id uuid NOT NULL,
 role varchar(12) NOT NULL CHECK (role IN ('user','assistant')),
 content text NOT NULL CHECK (octet_length(content)<=16000),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(owner_id,request_id) REFERENCES app.assistant_requests(owner_id,id),
 UNIQUE(owner_id,request_id,role)
);
CREATE INDEX ix_conversation_recent
 ON app.conversation_messages(owner_id,conversation_id,created_at);
CREATE TABLE app.llm_calls (
 id uuid PRIMARY KEY,
 owner_id uuid NOT NULL REFERENCES app.users(id),
 request_id uuid NOT NULL,
 kind varchar(12) NOT NULL CHECK (kind IN ('free','premium')),
 model varchar(200) NOT NULL,
 provider varchar(120) NOT NULL,
 status varchar(16) NOT NULL CHECK (status IN ('dispatching','succeeded','rejected','uncertain')),
 reserved_usd numeric(20,10) NOT NULL CHECK (reserved_usd>=0),
 actual_usd numeric(20,10) CHECK (actual_usd>=0),
 prompt_tokens integer CHECK (prompt_tokens>=0),
 completion_tokens integer CHECK (completion_tokens>=0),
 created_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz,
 FOREIGN KEY(owner_id,request_id) REFERENCES app.assistant_requests(owner_id,id),
 UNIQUE(owner_id,request_id,kind)
);
CREATE INDEX ix_llm_budget ON app.llm_calls(owner_id,created_at);;

REVOKE ALL ON app.assistant_state FROM PUBLIC;

GRANT SELECT,INSERT,UPDATE ON app.assistant_state TO jarvis_app;

ALTER TABLE app.assistant_state ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.assistant_state FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.assistant_state USING (owner_id=app.current_owner_id()) WITH CHECK (owner_id=app.current_owner_id());

REVOKE ALL ON app.profile_memory FROM PUBLIC;

GRANT SELECT,INSERT,UPDATE,DELETE ON app.profile_memory TO jarvis_app;

ALTER TABLE app.profile_memory ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.profile_memory FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.profile_memory USING (owner_id=app.current_owner_id()) WITH CHECK (owner_id=app.current_owner_id());

REVOKE ALL ON app.assistant_requests FROM PUBLIC;

GRANT SELECT,INSERT,UPDATE ON app.assistant_requests TO jarvis_app;

ALTER TABLE app.assistant_requests ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.assistant_requests FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.assistant_requests USING (owner_id=app.current_owner_id()) WITH CHECK (owner_id=app.current_owner_id());

REVOKE ALL ON app.conversation_messages FROM PUBLIC;

GRANT SELECT,INSERT,UPDATE,DELETE ON app.conversation_messages TO jarvis_app;

ALTER TABLE app.conversation_messages ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.conversation_messages FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.conversation_messages USING (owner_id=app.current_owner_id()) WITH CHECK (owner_id=app.current_owner_id());

REVOKE ALL ON app.llm_calls FROM PUBLIC;

GRANT SELECT,INSERT,UPDATE ON app.llm_calls TO jarvis_app;

ALTER TABLE app.llm_calls ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.llm_calls FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.llm_calls USING (owner_id=app.current_owner_id()) WITH CHECK (owner_id=app.current_owner_id());

UPDATE jarvis_schema_version SET version_num='0003_assistant' WHERE jarvis_schema_version.version_num = '0002_telegram';

-- Running upgrade 0003_assistant -> 0004_knowledge

CREATE TABLE app.knowledge_state (
 owner_id uuid PRIMARY KEY REFERENCES app.users(id), last_poll_at timestamptz
);
CREATE TABLE app.documents (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES app.users(id),
 title varchar(120) NOT NULL,
 kind varchar(8) NOT NULL CHECK (kind IN ('pdf','docx','png','jpg','jpeg')),
 data_class varchar(16) NOT NULL CHECK (data_class IN ('private','restricted')),
 sha256 varchar(64), pipeline varchar(64) NOT NULL,
 ocr varchar(8) NOT NULL CHECK (ocr IN ('auto','always','never')),
 status varchar(16) NOT NULL CHECK
   (status IN ('queued','processing','ready','failed','deleting','deleted')),
 byte_size bigint NOT NULL CHECK (byte_size BETWEEN 0 AND 20971520),
 attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
 lease_until timestamptz, lease_token uuid, error_code varchar(80),
 chunk_count integer NOT NULL DEFAULT 0 CHECK (chunk_count BETWEEN 0 AND 1500),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(owner_id,id)
);
CREATE UNIQUE INDEX ix_document_hash ON app.documents(owner_id,sha256,pipeline)
 WHERE status <> 'deleted';
CREATE INDEX ix_document_queue ON app.documents(owner_id,status,lease_until);
CREATE TABLE app.document_chunks (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES app.users(id),
 document_id uuid NOT NULL, ordinal integer NOT NULL CHECK (ordinal BETWEEN 0 AND 1499),
 locator varchar(120) NOT NULL, content text NOT NULL CHECK (octet_length(content)<=4800),
 UNIQUE(owner_id,document_id,ordinal),
 FOREIGN KEY(owner_id,document_id) REFERENCES app.documents(owner_id,id)
);
ALTER TABLE app.assistant_requests ADD COLUMN document_id uuid;
ALTER TABLE app.assistant_requests ADD COLUMN document_sources jsonb
 CHECK (octet_length(document_sources::text)<=65536);
ALTER TABLE app.assistant_requests ADD CONSTRAINT request_document_owner
 FOREIGN KEY(owner_id,document_id) REFERENCES app.documents(owner_id,id);
CREATE INDEX ix_request_document ON app.assistant_requests(owner_id,document_id);
ALTER TABLE app.telegram_receipts DROP CONSTRAINT telegram_receipts_reply_kind_check;
ALTER TABLE app.telegram_receipts ADD CONSTRAINT telegram_receipts_reply_kind_check
 CHECK (reply_kind IN ('unpaired','paired','pair_failed','already_paired','help','status',
 'privacy','unsupported','assistant','knowledge'));;

REVOKE ALL ON app.knowledge_state FROM PUBLIC;

GRANT SELECT,INSERT,UPDATE ON app.knowledge_state TO jarvis_app;

ALTER TABLE app.knowledge_state ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.knowledge_state FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.knowledge_state USING (owner_id=app.current_owner_id()) WITH CHECK (owner_id=app.current_owner_id());

REVOKE ALL ON app.documents FROM PUBLIC;

GRANT SELECT,INSERT,UPDATE ON app.documents TO jarvis_app;

ALTER TABLE app.documents ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.documents FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.documents USING (owner_id=app.current_owner_id()) WITH CHECK (owner_id=app.current_owner_id());

REVOKE ALL ON app.document_chunks FROM PUBLIC;

GRANT SELECT,INSERT,UPDATE,DELETE ON app.document_chunks TO jarvis_app;

ALTER TABLE app.document_chunks ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.document_chunks FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.document_chunks USING (owner_id=app.current_owner_id()) WITH CHECK (owner_id=app.current_owner_id());

UPDATE jarvis_schema_version SET version_num='0004_knowledge' WHERE jarvis_schema_version.version_num = '0003_assistant';

-- Running upgrade 0004_knowledge -> 0005_tool_actions

CREATE TABLE app.tool_actions (
 id uuid PRIMARY KEY,
 owner_id uuid NOT NULL REFERENCES app.users(id),
 request_id uuid,
 agent varchar(80) NOT NULL,
 tool_name varchar(80) NOT NULL,
 effect varchar(24) NOT NULL CHECK
   (effect IN ('read','reversible_write','external_send','destructive','high_impact')),
 arguments jsonb NOT NULL CHECK (octet_length(arguments::text)<=32768),
 action_fingerprint varchar(64) NOT NULL CHECK (action_fingerprint ~ '^[0-9a-f]{64}$'),
 status varchar(24) NOT NULL CHECK
   (status IN ('awaiting_approval','queued','claimed','dispatching','succeeded','failed',
               'uncertain','cancelled')),
 authorization_reason varchar(40) NOT NULL,
 approval_expires_at timestamptz,
 approved_at timestamptz,
 due_at timestamptz NOT NULL,
 attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
 lease_token uuid,
 lease_until timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz,
 UNIQUE(owner_id,id),
 FOREIGN KEY(owner_id,request_id) REFERENCES app.assistant_requests(owner_id,id)
);
CREATE INDEX ix_tool_action_queue ON app.tool_actions(owner_id,status,due_at,lease_until);
CREATE INDEX ix_tool_action_request ON app.tool_actions(owner_id,request_id);
REVOKE ALL ON app.tool_actions FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON app.tool_actions TO jarvis_app;
ALTER TABLE app.tool_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.tool_actions FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_isolation ON app.tool_actions
 USING (owner_id=app.current_owner_id())
 WITH CHECK (owner_id=app.current_owner_id());
CREATE FUNCTION app.reject_tool_action_payload_update() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
 IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
    OR NEW.request_id IS DISTINCT FROM OLD.request_id
    OR NEW.agent IS DISTINCT FROM OLD.agent
    OR NEW.tool_name IS DISTINCT FROM OLD.tool_name
    OR NEW.effect IS DISTINCT FROM OLD.effect
    OR NEW.arguments IS DISTINCT FROM OLD.arguments
    OR NEW.action_fingerprint IS DISTINCT FROM OLD.action_fingerprint
    OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
   RAISE EXCEPTION 'tool action payload is immutable';
 END IF;
 RETURN NEW;
END; $$;
REVOKE ALL ON FUNCTION app.reject_tool_action_payload_update() FROM PUBLIC;
CREATE TRIGGER tool_action_payload_immutable
 BEFORE UPDATE ON app.tool_actions
 FOR EACH ROW EXECUTE FUNCTION app.reject_tool_action_payload_update();;

UPDATE jarvis_schema_version SET version_num='0005_tool_actions' WHERE jarvis_schema_version.version_num = '0004_knowledge';

-- Running upgrade 0005_tool_actions -> 0006_tool_action_timezone

ALTER TABLE app.tool_actions ADD COLUMN due_timezone varchar(64) NOT NULL DEFAULT 'UTC';
    ALTER TABLE app.tool_actions ALTER COLUMN due_timezone DROP DEFAULT;
    ALTER TABLE app.tool_actions ADD CONSTRAINT tool_action_due_timezone_nonempty
      CHECK (length(due_timezone) BETWEEN 1 AND 64 AND due_timezone !~ '[\r\n\x00]');
    CREATE OR REPLACE FUNCTION app.reject_tool_action_payload_update() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
     IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
        OR NEW.request_id IS DISTINCT FROM OLD.request_id
        OR NEW.agent IS DISTINCT FROM OLD.agent
        OR NEW.tool_name IS DISTINCT FROM OLD.tool_name
        OR NEW.effect IS DISTINCT FROM OLD.effect
        OR NEW.arguments IS DISTINCT FROM OLD.arguments
        OR NEW.action_fingerprint IS DISTINCT FROM OLD.action_fingerprint
        OR NEW.due_at IS DISTINCT FROM OLD.due_at
        OR NEW.due_timezone IS DISTINCT FROM OLD.due_timezone
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
       RAISE EXCEPTION 'tool action payload is immutable';
     END IF;
     RETURN NEW;
    END; $$;;

UPDATE jarvis_schema_version SET version_num='0006_tool_action_timezone' WHERE jarvis_schema_version.version_num = '0005_tool_actions';

-- Running upgrade 0006_tool_action_timezone -> 0007_action_authority

CREATE TABLE app.tool_grants (
      owner_id uuid NOT NULL REFERENCES app.users(id),
      agent varchar(80) NOT NULL,
      scopes text[] NOT NULL,
      enabled boolean NOT NULL DEFAULT false,
      revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
      updated_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY(owner_id, agent)
    );
    REVOKE ALL ON app.tool_grants FROM PUBLIC;
    GRANT SELECT,INSERT,UPDATE ON app.tool_grants TO jarvis_app;
    ALTER TABLE app.tool_grants ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.tool_grants FORCE ROW LEVEL SECURITY;
    CREATE POLICY owner_isolation ON app.tool_grants
      USING (owner_id=app.current_owner_id()) WITH CHECK (owner_id=app.current_owner_id());
    ALTER TABLE app.tool_actions
      ADD COLUMN source_key varchar(200),
      ADD COLUMN grant_revision integer,
      ADD COLUMN spec_fingerprint varchar(64),
      ADD COLUMN result jsonb,
      ADD COLUMN error_code varchar(80),
      ADD CONSTRAINT tool_result_bound CHECK (octet_length(result::text)<=32768),
      ADD CONSTRAINT tool_action_source_unique UNIQUE(owner_id,source_key);
    -- Old actions have no durable grant. Never silently grant them new authority.
    ALTER TABLE app.tool_actions NO FORCE ROW LEVEL SECURITY;
    UPDATE app.tool_actions SET status='cancelled', finished_at=now(),
      lease_token=NULL, lease_until=NULL, error_code='legacy_authority_missing'
      WHERE status IN ('queued','claimed','awaiting_approval');
    UPDATE app.tool_actions SET status='uncertain', finished_at=now(),
      lease_token=NULL, lease_until=NULL, error_code='legacy_dispatch_uncertain'
      WHERE status='dispatching';
    ALTER TABLE app.tool_actions FORCE ROW LEVEL SECURITY;
    CREATE OR REPLACE FUNCTION app.reject_tool_action_payload_update() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
      IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
        OR NEW.request_id IS DISTINCT FROM OLD.request_id
        OR NEW.agent IS DISTINCT FROM OLD.agent
        OR NEW.tool_name IS DISTINCT FROM OLD.tool_name
        OR NEW.effect IS DISTINCT FROM OLD.effect
        OR NEW.arguments IS DISTINCT FROM OLD.arguments
        OR NEW.action_fingerprint IS DISTINCT FROM OLD.action_fingerprint
        OR NEW.due_at IS DISTINCT FROM OLD.due_at
        OR NEW.due_timezone IS DISTINCT FROM OLD.due_timezone
        OR NEW.source_key IS DISTINCT FROM OLD.source_key
        OR NEW.grant_revision IS DISTINCT FROM OLD.grant_revision
        OR NEW.spec_fingerprint IS DISTINCT FROM OLD.spec_fingerprint
        OR NEW.authorization_reason IS DISTINCT FROM OLD.authorization_reason
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'tool action payload is immutable';
      END IF;
      RETURN NEW;
    END; $$;;

UPDATE jarvis_schema_version SET version_num='0007_action_authority' WHERE jarvis_schema_version.version_num = '0006_tool_action_timezone';

-- Running upgrade 0007_action_authority -> 0008_executor_binding

ALTER TABLE app.tool_grants
      ADD COLUMN binding_fingerprint varchar(64),
      ADD COLUMN last_poll_at timestamptz,
      ADD CONSTRAINT tool_grant_binding_format CHECK
        (binding_fingerprint IS NULL OR binding_fingerprint ~ '^[0-9a-f]{64}$');;

UPDATE jarvis_schema_version SET version_num='0008_executor_binding' WHERE jarvis_schema_version.version_num = '0007_action_authority';

-- Running upgrade 0008_executor_binding -> 0009_calendar_tasks

ALTER TABLE app.assistant_requests DROP CONSTRAINT assistant_requests_status_check;
    ALTER TABLE app.assistant_requests ADD CONSTRAINT assistant_requests_status_check
      CHECK (status IN ('queued','preparing','awaiting_approval','approved','dispatching',
        'succeeded','failed','uncertain','cancelled','clarified','handed_off'));
    -- Keep ix_one_assistant_request: LLM calls still have one active turn per owner.
    ALTER TABLE app.tool_actions
      ADD COLUMN fingerprint_version integer NOT NULL DEFAULT 1
        CHECK (fingerprint_version IN (1,2)),
      ADD COLUMN latest_dispatch_at timestamptz,
      ADD CONSTRAINT tool_dispatch_window CHECK
        (latest_dispatch_at IS NULL OR latest_dispatch_at > due_at),
      ADD CONSTRAINT tool_schedule_binding CHECK
        (fingerprint_version = 1 OR latest_dispatch_at IS NOT NULL);
    ALTER TABLE app.external_identities ADD CONSTRAINT identity_owner_id UNIQUE(owner_id,id);
    CREATE TABLE app.calendar_tasks (
      id uuid PRIMARY KEY,
      owner_id uuid NOT NULL REFERENCES app.users(id),
      bot_id bigint NOT NULL,
      chat_id bigint NOT NULL CHECK (chat_id > 0),
      identity_id uuid NOT NULL,
      conversation_id uuid NOT NULL,
      source_request_id uuid NOT NULL,
      state_revision integer NOT NULL CHECK (state_revision > 0),
      config_hash varchar(64) NOT NULL,
      grant_revision integer NOT NULL CHECK (grant_revision > 0),
      revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
      channel varchar(16) NOT NULL CHECK (channel='telegram'),
      anchor_at timestamptz NOT NULL,
      timezone varchar(64) NOT NULL,
      slots jsonb NOT NULL CHECK (octet_length(slots::text)<=12000),
      provenance jsonb NOT NULL CHECK (octet_length(provenance::text)<=24000),
      status varchar(24) NOT NULL CHECK
        (status IN ('draft','submitted','succeeded','failed','cancelled','uncertain','expired')),
      current_action_id uuid,
      expires_at timestamptz NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(owner_id,id),
      FOREIGN KEY(owner_id,identity_id) REFERENCES app.external_identities(owner_id,id),
      FOREIGN KEY(owner_id,source_request_id) REFERENCES app.assistant_requests(owner_id,id),
      FOREIGN KEY(owner_id,current_action_id) REFERENCES app.tool_actions(owner_id,id),
      FOREIGN KEY(owner_id,bot_id) REFERENCES app.telegram_state(owner_id,bot_id)
    );
    CREATE INDEX ix_calendar_drafts ON app.calendar_tasks(owner_id,conversation_id,status);
    CREATE TABLE app.calendar_notifications (
      id uuid PRIMARY KEY,
      owner_id uuid NOT NULL REFERENCES app.users(id),
      bot_id bigint NOT NULL,
      chat_id bigint NOT NULL,
      task_id uuid NOT NULL,
      action_id uuid NOT NULL,
      event_key varchar(100) NOT NULL,
      reply_text text CHECK (octet_length(reply_text)<=16000),
      delivery_status varchar(16) NOT NULL CHECK
        (delivery_status IN ('pending','sending','sent','uncertain','failed','blocked','expired')),
      attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
      next_attempt_at timestamptz NOT NULL,
      telegram_message_id bigint,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(owner_id,event_key),
      FOREIGN KEY(owner_id,bot_id) REFERENCES app.telegram_state(owner_id,bot_id),
      FOREIGN KEY(owner_id,task_id) REFERENCES app.calendar_tasks(owner_id,id),
      FOREIGN KEY(owner_id,action_id) REFERENCES app.tool_actions(owner_id,id)
    );
    CREATE INDEX ix_calendar_notification_pending
      ON app.calendar_notifications(owner_id,bot_id,delivery_status,next_attempt_at);
    CREATE OR REPLACE FUNCTION app.reject_tool_action_payload_update() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog AS $$
    BEGIN
      IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
        OR NEW.request_id IS DISTINCT FROM OLD.request_id
        OR NEW.agent IS DISTINCT FROM OLD.agent
        OR NEW.tool_name IS DISTINCT FROM OLD.tool_name
        OR NEW.effect IS DISTINCT FROM OLD.effect
        OR NEW.arguments IS DISTINCT FROM OLD.arguments
        OR NEW.action_fingerprint IS DISTINCT FROM OLD.action_fingerprint
        OR NEW.due_at IS DISTINCT FROM OLD.due_at
        OR NEW.due_timezone IS DISTINCT FROM OLD.due_timezone
        OR NEW.fingerprint_version IS DISTINCT FROM OLD.fingerprint_version
        OR NEW.latest_dispatch_at IS DISTINCT FROM OLD.latest_dispatch_at
        OR NEW.source_key IS DISTINCT FROM OLD.source_key
        OR NEW.grant_revision IS DISTINCT FROM OLD.grant_revision
        OR NEW.spec_fingerprint IS DISTINCT FROM OLD.spec_fingerprint
        OR NEW.authorization_reason IS DISTINCT FROM OLD.authorization_reason
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'tool action payload is immutable';
      END IF;
      RETURN NEW;
    END; $$;;

REVOKE ALL ON app.calendar_tasks FROM PUBLIC;

GRANT SELECT,INSERT,UPDATE ON app.calendar_tasks TO jarvis_app;

ALTER TABLE app.calendar_tasks ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.calendar_tasks FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.calendar_tasks USING (owner_id=app.current_owner_id()) WITH CHECK (owner_id=app.current_owner_id());

REVOKE ALL ON app.calendar_notifications FROM PUBLIC;

GRANT SELECT,INSERT,UPDATE ON app.calendar_notifications TO jarvis_app;

ALTER TABLE app.calendar_notifications ENABLE ROW LEVEL SECURITY;

ALTER TABLE app.calendar_notifications FORCE ROW LEVEL SECURITY;

CREATE POLICY owner_isolation ON app.calendar_notifications USING (owner_id=app.current_owner_id()) WITH CHECK (owner_id=app.current_owner_id());

UPDATE jarvis_schema_version SET version_num='0009_calendar_tasks' WHERE jarvis_schema_version.version_num = '0008_executor_binding';

COMMIT;

