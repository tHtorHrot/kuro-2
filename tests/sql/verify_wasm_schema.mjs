// Supplementary SQL verification only; native PostgreSQL integration is mandatory in CI.
// node this-file.mjs /absolute/path/pglite/dist/index.js /absolute/path/migration.sql
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const { PGlite } = await import(pathToFileURL(process.argv[2]).href);
const migration = await readFile(process.argv[3], 'utf8');
const db = new PGlite();
let checks = 0;
const check = (value) => { assert(value); checks++; };
const count = async (table) => (await db.query(`SELECT count(*)::int AS n FROM app.${table}`)).rows[0].n;
const tenant = async (id) => {
  await db.exec('BEGIN');
  await db.query("SELECT set_config('jarvis.owner_id', $1, true)", [id]);
};
const mustFail = async (sql) => {
  let rejected = false;
  try { await db.exec(sql); } catch { rejected = true; }
  assert(rejected, `SQL should be denied: ${sql}`); checks++;
  await db.exec('ROLLBACK');
};
try {
  const engine = (await db.query('SELECT version() AS version')).rows[0].version;
  await db.exec('CREATE ROLE jarvis_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT');
  await db.exec('CREATE ROLE jarvis_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT');
  await db.exec("DO $$ BEGIN EXECUTE format('GRANT CREATE ON DATABASE %I TO jarvis_migrator', current_database()); END $$;");
  await db.exec(`
    REVOKE ALL ON SCHEMA public FROM PUBLIC;
    GRANT USAGE, CREATE ON SCHEMA public TO jarvis_migrator;
    GRANT USAGE ON SCHEMA public TO jarvis_app;
    SET ROLE jarvis_migrator;
  `);
  await db.exec(migration);
  check((await db.query('SELECT version_num FROM public.jarvis_schema_version')).rows[0].version_num === '0017_task_role_documents');
  // SET ROLE alone would leave a superuser session authorized to switch roles again.
  await db.exec('RESET ROLE; SET SESSION AUTHORIZATION jarvis_app');
  const a = '00000000-0000-4000-8000-000000000001';
  const b = '00000000-0000-4000-8000-000000000002';
  for (const id of [a, b]) {
    await tenant(id);
    await db.query("INSERT INTO app.users(id,display_name,timezone) VALUES ($1,'SQL test','Asia/Jakarta')", [id]);
    check(await count('users') === 1);
    await db.exec('COMMIT');
  }
  check(await count('users') === 0);
  for (const table of ['api_tokens', 'pairing_codes', 'external_identities', 'audit_events', 'telegram_state', 'telegram_receipts']) {
    check(await count(table) === 0);
  }
  await tenant(a);
  check((await db.query('SELECT id FROM app.users')).rows[0].id === a);
  check((await db.query("UPDATE app.users SET display_name='forbidden' WHERE id=$1 RETURNING id", [b])).rows.length === 0);
  await db.exec('COMMIT');
  await tenant(a);
  await mustFail("INSERT INTO app.users(id,display_name,timezone) VALUES ('00000000-0000-4000-8000-000000000003','bad','UTC')");
  await tenant(a);
  await db.query("INSERT INTO app.audit_events(id,owner_id,action) VALUES ($1,$1,'test')", [a]);
  await db.exec('COMMIT');
  for (const sql of ["UPDATE app.audit_events SET action='bad'", 'DELETE FROM app.audit_events',
                     'CREATE TABLE app.forbidden(id int)', 'SET ROLE jarvis_migrator']) {
    await tenant(a);
    await mustFail(sql);
  }
  check((await db.query("SELECT app.current_owner_id() AS id")).rows[0].id === null);
  const security = await db.query("SELECT bool_and(relrowsecurity AND relforcerowsecurity) AS secured, count(*)::int AS n FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='app' AND c.relkind='r'");
  check(security.rows[0].secured && security.rows[0].n === 28);
  await tenant(a);
  await db.query("INSERT INTO app.telegram_state(owner_id,bot_id,rate_window_at) VALUES ($1,100,now())", [a]);
  await db.query("INSERT INTO app.telegram_receipts(owner_id,bot_id,update_id,chat_id,reply_kind,delivery_status,next_attempt_at) VALUES ($1,100,1000,111,'status','pending',now())", [a]);
  check(await count('telegram_receipts') === 1);
  await db.exec('COMMIT');
  await tenant(b);
  check(await count('telegram_state') === 0);
  check(await count('telegram_receipts') === 0);
  await mustFail(`INSERT INTO app.telegram_receipts(owner_id,bot_id,update_id,chat_id,delivery_status,next_attempt_at) VALUES ('${a}',100,1001,111,'pending',now())`);
  await tenant(a);
  await mustFail("UPDATE app.telegram_receipts SET reply_kind='arbitrary-user-text'");
  await tenant(a);
  await mustFail("UPDATE app.telegram_receipts SET attempts=6");
  await tenant(a);
  await mustFail("UPDATE app.telegram_receipts SET delivery_status='unrecognized'");
  await tenant(a);
  await mustFail("UPDATE app.telegram_receipts SET bot_id=999");
  await tenant(a);
  await mustFail("DELETE FROM app.telegram_state");
  await tenant(a);
  await db.exec("DELETE FROM app.telegram_receipts");
  check(await count('telegram_receipts') === 0);
  check(await count('telegram_state') === 1);
  await db.exec('COMMIT');
  check(await count('telegram_state') === 0);
  const tables = ['assistant_state','profile_memory','assistant_requests','conversation_messages','llm_calls'];
  for (const table of tables) check(await count(table) === 0);
  const request = '00000000-0000-4000-8000-000000000011';
  await tenant(a);
  await db.query("INSERT INTO app.assistant_state(owner_id,conversation_id,config_hash) VALUES ($1,$1,'hash')", [a]);
  await db.query("INSERT INTO app.profile_memory(owner_id,key,value) VALUES ($1,'nama','Private owner A')", [a]);
  await db.query("INSERT INTO app.assistant_requests(id,owner_id,bot_id,source_update_id,reply_update_id,conversation_id,revision,config_hash,prompt,status) VALUES ($1,$2,100,200,200,$2,1,'hash','private prompt','queued')", [request,a]);
  await db.query("INSERT INTO app.llm_calls(id,owner_id,request_id,kind,model,provider,status,reserved_usd) VALUES ($1,$2,$1,'premium','qwen/paid','test','dispatching',0.005)", [request,a]);
  await db.query("INSERT INTO app.conversation_messages(id,owner_id,conversation_id,request_id,role,content) VALUES ($1,$2,$2,$1,'user','private text')", [request,a]);
  for (const table of tables) check(await count(table) === 1);
  await db.exec('COMMIT');
  await tenant(b);
  for (const table of tables) check(await count(table) === 0);
  await mustFail(`INSERT INTO app.profile_memory(owner_id,key,value) VALUES ('${a}','foreign','forbidden')`);
  await tenant(a);
  await mustFail(`INSERT INTO app.assistant_requests(id,owner_id,bot_id,source_update_id,reply_update_id,conversation_id,revision,config_hash,status) VALUES (gen_random_uuid(),'${a}',100,201,201,'${a}',1,'hash','queued')`);
  await tenant(a);
  await mustFail(`INSERT INTO app.llm_calls(id,owner_id,request_id,kind,model,provider,status,reserved_usd) VALUES (gen_random_uuid(),'${a}','${request}','premium','qwen/paid','test','dispatching',0.005)`);
  await tenant(a);
  await mustFail('UPDATE app.llm_calls SET reserved_usd=-1');
  await tenant(a);
  await mustFail('DELETE FROM app.llm_calls');
  await tenant(a);
  await mustFail("UPDATE app.profile_memory SET data_class='public'");
  await tenant(a);
  await db.exec("UPDATE app.assistant_requests SET status='cancelled',prompt=NULL,messages=NULL; DELETE FROM app.conversation_messages; DELETE FROM app.profile_memory;");
  check(await count('llm_calls') === 1);
  check(await count('conversation_messages') === 0);
  await db.exec('COMMIT');
  const doc = '00000000-0000-4000-8000-000000000031';
  const foreignDoc = '00000000-0000-4000-8000-000000000032';
  for (const [owner, id] of [[a,doc],[b,foreignDoc]]) {
    await tenant(owner);
    await db.query("INSERT INTO app.knowledge_state(owner_id,last_poll_at) VALUES ($1,now())", [owner]);
    await db.query("INSERT INTO app.documents(id,owner_id,title,kind,data_class,sha256,pipeline,ocr,status,byte_size) VALUES ($1,$2,'fixture','docx','private','sha','pipeline','auto','queued',12)", [id,owner]);
    await db.query("INSERT INTO app.document_chunks(id,owner_id,document_id,ordinal,locator,content) VALUES ($1,$2,$1,0,'paragraf 1','PRIVATE fixture')", [id,owner]);
    for(const table of ['knowledge_state','documents','document_chunks']) check(await count(table) === 1);
    await db.exec('COMMIT');
  }
  for(const table of ['knowledge_state','documents','document_chunks']) check(await count(table) === 0);
  await tenant(a);
  check((await db.query('SELECT id FROM app.documents')).rows[0].id === doc);
  await mustFail(`UPDATE app.assistant_requests SET document_id='${foreignDoc}'`);
  await tenant(a);
  await mustFail(`INSERT INTO app.document_chunks(id,owner_id,document_id,ordinal,locator,content) VALUES (gen_random_uuid(),'${a}','${foreignDoc}',1,'p1','foreign')`);
  for(const sql of ["UPDATE app.documents SET attempts=4", "UPDATE app.documents SET status='unknown'", "UPDATE app.documents SET byte_size=20971521", "DELETE FROM app.documents"]) {
    await tenant(a); await mustFail(sql);
  }
  await tenant(a);
  await db.query("UPDATE app.assistant_requests SET document_id=$1,document_sources='[]'::jsonb", [doc]);
  await db.query("UPDATE app.documents SET status='deleting' WHERE id=$1", [doc]);
  await db.exec('UPDATE app.assistant_requests SET document_sources=NULL');
  check((await db.query('SELECT document_sources IS NULL AS erased FROM app.assistant_requests')).rows[0].erased);
  await db.query('DELETE FROM app.document_chunks WHERE document_id=$1', [doc]);
  check(await count('document_chunks') === 0);
  await db.exec('COMMIT');
  const action = '00000000-0000-4000-8000-000000000041';
  await tenant(a);
  await db.query("INSERT INTO app.tool_actions(id,owner_id,agent,tool_name,effect,arguments,action_fingerprint,status,authorization_reason,due_at,due_timezone) VALUES ($1,$2,'calendar','calendar_read','read','{\"date\":\"today\"}'::jsonb,$3,'queued','read_only',now(),'UTC')", [action,a,'a'.repeat(64)]);
  check(await count('tool_actions') === 1);
  await db.exec('COMMIT');
  await tenant(b);
  check(await count('tool_actions') === 0);
  await db.exec('COMMIT');
  await tenant(a);
  await mustFail("UPDATE app.tool_actions SET arguments='{\"date\":\"tomorrow\"}'::jsonb");
  const task = '00000000-0000-4000-8000-000000000051';
  const identity = '00000000-0000-4000-8000-000000000052';
  const notification = '00000000-0000-4000-8000-000000000053';
  await tenant(a);
  await db.query("INSERT INTO app.external_identities(id,owner_id,channel,external_user_id,chat_id) VALUES ($1,$2,'telegram',111,111)", [identity,a]);
  await db.query("UPDATE app.assistant_requests SET status='handed_off' WHERE id=$1", [request]);
  await db.query("INSERT INTO app.calendar_tasks(id,owner_id,bot_id,chat_id,identity_id,conversation_id,source_request_id,state_revision,config_hash,grant_revision,revision,channel,anchor_at,timezone,slots,provenance,status,current_action_id,expires_at) VALUES ($1,$2,100,111,$3,$2,$4,1,'hash',1,1,'telegram',now(),'Asia/Jakarta','{}','{}','submitted',$5,now()+interval '30 minutes')", [task,a,identity,request,action]);
  await db.query("INSERT INTO app.calendar_notifications(id,owner_id,bot_id,chat_id,task_id,action_id,event_key,reply_text,delivery_status,next_attempt_at) VALUES ($1,$2,100,111,$3,$4,'terminal-fixture','result','pending',now())", [notification,a,task,action]);
  check(await count('calendar_tasks') === 1);
  check(await count('calendar_notifications') === 1);
  await db.exec('COMMIT');
  await tenant(b);
  check(await count('calendar_tasks') === 0);
  check(await count('calendar_notifications') === 0);
  await mustFail(`INSERT INTO app.calendar_notifications(id,owner_id,bot_id,chat_id,task_id,action_id,event_key,delivery_status,next_attempt_at) VALUES (gen_random_uuid(),'${b}',100,111,'${task}','${action}','cross-owner','pending',now())`);
  await tenant(a);
  await mustFail(`UPDATE app.calendar_notifications SET attempts=6 WHERE id='${notification}'`);
  await tenant(a);
  await mustFail(`INSERT INTO app.calendar_notifications(id,owner_id,bot_id,chat_id,task_id,action_id,event_key,delivery_status,next_attempt_at) VALUES (gen_random_uuid(),'${a}',100,111,'${task}','${action}','terminal-fixture','pending',now())`);
  await tenant(a);
  await mustFail(`UPDATE app.tool_actions SET fingerprint_version=2, latest_dispatch_at=due_at+interval '15 minutes' WHERE id='${action}'`);
  await tenant(a);
  await mustFail(`DELETE FROM app.calendar_tasks WHERE id='${task}'`);
  await tenant(a);
  await db.query("INSERT INTO app.assistant_requests(id,owner_id,bot_id,source_update_id,reply_update_id,conversation_id,revision,config_hash,status) VALUES (gen_random_uuid(),$1,100,300,300,$1,1,'hash','queued')", [a]);
  check(await count('assistant_requests') === 2); // Detached job does not consume the LLM slot.
  await db.exec('COMMIT');
  await tenant(a);
  await db.query("INSERT INTO app.projects(owner_id,name) VALUES ($1,'proyek-a')", [a]);
  await db.query("INSERT INTO app.project_state(owner_id,active_project) VALUES ($1,'proyek-a')", [a]);
  await db.query("INSERT INTO app.profile_memory(owner_id,key,value,project) VALUES ($1,'tugas-a','rahasia a','proyek-a')", [a]);
  check(await count('projects') === 1);
  await db.exec('COMMIT');
  await tenant(b);
  check(await count('projects') === 0);
  check(await count('profile_memory') === 0);
  await mustFail(`INSERT INTO app.profile_memory(owner_id,key,value,project) VALUES ('${b}','tugas-a','forbidden','proyek-a')`);
  await tenant(a);
  await db.exec('COMMIT');
  console.log(JSON.stringify({ status: 'passed', checks, engine, limitation: 'WASM SQL only; not native PostgreSQL 16, networking, pooling or concurrency verification' }));
} finally {
  await db.close();
}
