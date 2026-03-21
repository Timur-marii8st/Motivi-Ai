# Test Coverage Inspection Report

**Date:** 2026-03-21
**Scope:** All test files in `tests/`, cross-referenced against services, routers, LLM logic, security, and scheduler modules.

---

## Overall Coverage Health Score: 12/100

**Justification:** The project has 6 test files containing approximately 20 test functions total. These cover a tiny fraction of the codebase: basic job scheduling, core memory storage/retrieval, encryption type round-tripping, reminder tool CRUD, and row integrity signatures. The vast majority of critical business logic -- the entire ReAct loop, all 19 routers, subscription/payment flows, the code executor, web search, userbot monitoring, proactive flows, fact extraction, account deletion, conversation history, and all integration paths -- have zero test coverage. For a production system handling user data with encryption, financial transactions (Telegram Stars), and external API integrations, this is a critical gap.

---

## Existing Test Quality Assessment

### tests/conftest.py
- Contains only `sys.path` manipulation. No fixtures, no DB setup, no mock factories.
- **Issue:** Every test file independently creates its own mocks/fakes with significant duplication (FakeUser, FakeSession, etc. redefined in every file).

### tests/test_job_manager.py (2 tests)
- `test_schedule_user_jobs_registers_cron_jobs` -- Verifies morning/evening job registration and fire times. Adequate for the happy path.
- `test_evening_wrapup_job_calls_flow_when_not_in_break_mode` -- Verifies ProactiveFlows is called. Good.
- **Gaps:** No test for weekly/monthly/news_digest job registration. No test for `schedule_user_triggers`. No test for `schedule_habit_reminders`. No test for `remove_user_jobs`. No test for edge case where `user_timezone` is None (should skip). No test for midnight rollover in evening time calculation (bed_time.hour == 0).

### tests/test_memory_orchestrator_and_core_memory.py (4 tests)
- Tests MemoryPack serialization, CoreMemoryService store/retrieve, and MemoryOrchestrator assembly. Reasonable unit-level coverage of the happy path.
- **Issue:** Massive mock duplication (lines 106-135: `fake_exec_result` assigned 9 times, `fake_session.execute` assigned 9 times). This is dead code that suggests copy-paste development.
- **Gap:** No test for empty core facts, empty episodes, stale working memory flag in `to_context_dict()`, or what happens when embeddings API fails.

### tests/test_scheduler_and_encryption.py (8 tests)
- Good breadth: cleanup job trigger, morning/evening/weekly/monthly job execution with break mode, one-off reminder delivery, habit reminder, cleanup expired memories, encryption round-trip.
- **Issue in `test_evening_weekly_monthly_jobs_skip_on_break_mode`:** Asserts `fake_session.commit.assert_not_awaited()` but the refactored `_run_proactive_job` always calls `session.close()` which is not checked. Tests may pass against stale code.
- **Gap:** `test_cleanup_expired_memories_job_basic_flow` only verifies `execute.await_count >= 2` and `commit.await_count >= 1` -- does not verify correct SQL is issued or that episode embeddings are deleted before episodes.

### tests/test_scheduler_reminder_tool.py (4 tests)
- Good coverage of reminder scheduling: timezone handling, past-time rejection, explicit timezone, async job execution.
- **Issue:** `test_scheduler_job_runs_async` uses `asyncio.wait_for(event.wait(), timeout=10)` -- this is a 10-second timeout that makes the test slow and potentially flaky in CI.
- **Gap:** No test for canceling a reminder belonging to a different user (security check). No test for listing reminders when none exist.

### tests/test_row_integrity.py (4 tests)
- Clean, well-structured tests. Covers strict mode rejection, non-strict allowance, tampering detection, and valid signature pass-through.
- **Gap:** No test for `_before_flush` SQLAlchemy event hook (the actual integration point). No test for `register_row_integrity_hooks` on-load verification. No test for `_normalize` edge cases (nested dicts, None values).

---

## Critical Coverage Gaps

### 1. ConversationService ReAct Loop (`app/llm/conversation_service.py`)
**Risk Level: CRITICAL**
Zero test coverage for the core LLM interaction engine.

| What breaks if untested | Impact |
|---|---|
| Infinite tool-calling loop | Bot hangs, burns API credits |
| JSON parse errors in tool arguments | Silent failures, broken user experience |
| Max iterations fallback message | Users get Russian text regardless of language setting |
| History filtering drops user messages | Context loss across turns |
| ProfileCompletenessService side effects | Completeness scoring breaks silently |

**Recommended tests:**
| Test name | Type | What it verifies |
|---|---|---|
| `test_react_loop_no_tool_calls_returns_text` | unit | LLM response with no tools yields final text |
| `test_react_loop_single_tool_call_then_text` | unit | One tool call followed by final response |
| `test_react_loop_max_iterations_fallback` | unit | Hits max_iterations, returns fallback message |
| `test_react_loop_malformed_json_tool_args` | unit | Bad JSON in tool arguments produces error tool message |
| `test_react_loop_forced_tool_choice_first_iteration_only` | unit | forced_tool_choice applies only on iteration 1 |
| `test_history_filtering_excludes_system_and_tool_messages` | unit | Only user/assistant text in saved history |
| `test_exception_returns_friendly_error` | unit | Exception yields user-friendly message, not traceback |
| `test_clean_json_strips_markdown_code_blocks` | unit | `_clean_json` handles ```json blocks |
| `test_persona_fallback_when_file_missing` | unit | Missing persona file falls back to legacy prompt |

### 2. ToolExecutor -- All 11 Tool Handlers (`app/services/tool_executor.py`)
**Risk Level: CRITICAL**
Only reminder tools (schedule/cancel/list) have tests. 8 tools are untested.

| Untested tool | Risk if broken |
|---|---|
| `create_plan` | Plans silently not created, user gets no confirmation |
| `check_plan` | Wrong plans returned or crash on empty results |
| `edit_plan` | Editing expired plans, editing another user's plan |
| `create_calendar_event` | Google Calendar integration silently fails |
| `check_calendar_availability` | Wrong availability reported |
| `execute_code` | Rate limiting bypassed, subscription gate broken |
| `load_skill` | Wrong skill loaded, missing skill not handled |
| `web_search` | Rate limiting bypassed, subscription gate broken |
| `execute` dispatch | Unknown tool names not handled gracefully |

**Recommended tests:**
| Test name | Type |
|---|---|
| `test_create_plan_happy_path` | unit |
| `test_create_plan_invalid_level_rejected` | unit |
| `test_check_plan_returns_active_only` | unit |
| `test_edit_plan_expired_rejected` | unit |
| `test_edit_plan_wrong_user_rejected` | unit |
| `test_execute_code_expired_user_blocked` | unit |
| `test_execute_code_rate_limit_enforced` | unit |
| `test_execute_code_unsupported_language` | unit |
| `test_web_search_expired_user_blocked` | unit |
| `test_web_search_rate_limit_enforced` | unit |
| `test_load_skill_unknown_name` | unit |
| `test_load_skill_returns_content` | unit |
| `test_execute_unknown_tool_returns_error` | unit |

### 3. CodeExecutorService (`app/services/code_executor_service.py`)
**Risk Level: CRITICAL**
Zero test coverage for the sandboxed Docker execution engine.

| What breaks if untested | Impact |
|---|---|
| Docker command construction errors | Security controls bypassed (network, memory, caps) |
| Output file collection symlink traversal | Path traversal vulnerability |
| Timeout handling | Containers not killed, resource leak |
| File size/count limits | OOM or disk exhaustion |
| Unsupported language handling | Crash instead of graceful error |

**Recommended tests:**
| Test name | Type |
|---|---|
| `test_build_docker_cmd_contains_security_flags` | unit |
| `test_build_docker_cmd_with_output_dir_mount` | unit |
| `test_collect_output_files_skips_symlinks` | unit |
| `test_collect_output_files_respects_max_count` | unit |
| `test_collect_output_files_respects_max_size` | unit |
| `test_collect_output_files_filters_extensions` | unit |
| `test_run_unsupported_language` | unit |
| `test_code_execution_result_to_dict` | unit |
| `test_code_execution_result_format_for_chat` | unit |
| `test_run_timeout_kills_container` | integration |
| `test_run_python_with_file_output` | integration |

### 4. Subscription & Payment Flows (`app/services/subscription_service.py`)
**Risk Level: HIGH**
Zero test coverage. Financial logic.

| What breaks | Impact |
|---|---|
| `get_user_status` wrong result | Users get wrong tier, free access or wrongful blocks |
| `check_quota` counter logic | Rate limits bypassed or users wrongfully blocked |
| `add_subscription_time` date math | Subscription periods calculated wrong, revenue loss |

**Recommended tests:**
| Test name | Type |
|---|---|
| `test_get_user_status_admin` | unit |
| `test_get_user_status_premium` | unit |
| `test_get_user_status_trial` | unit |
| `test_get_user_status_expired` | unit |
| `test_check_quota_allows_within_limit` | unit |
| `test_check_quota_blocks_over_limit` | unit |
| `test_check_quota_admin_bypasses_limit` | unit |
| `test_add_subscription_time_new_user` | unit |
| `test_add_subscription_time_extends_existing` | unit |

### 5. HabitService -- Streak Tracking (`app/services/habit_service.py`)
**Risk Level: HIGH**
Zero test coverage for complex streak calculation logic.

| What breaks | Impact |
|---|---|
| `_calculate_daily_streak` gaps | Wrong streak counts, demotivated users |
| `_calculate_weekly_streak` year boundary | Streak resets at year end (known edge case in code) |
| `log_habit` duplicate date handling | Double-counting or crash |
| `_update_streak` with empty logs | Potential crash |

**Recommended tests:**
| Test name | Type |
|---|---|
| `test_daily_streak_consecutive_days` | unit |
| `test_daily_streak_with_gap` | unit |
| `test_daily_streak_single_day` | unit |
| `test_daily_streak_empty_logs` | unit |
| `test_weekly_streak_consecutive_weeks` | unit |
| `test_weekly_streak_year_boundary` | unit |
| `test_log_habit_creates_new_log` | unit |
| `test_log_habit_increments_existing_log` | unit |
| `test_log_habit_nonexistent_habit_raises` | unit |
| `test_archive_habit_sets_inactive` | unit |

### 6. All Bot Routers (19 routers, 0 tests)
**Risk Level: HIGH**
`app/bot/routers/` -- zero router tests exist.

| Router | Key untested behavior |
|---|---|
| `chat.py` | Main message handler, quota check, memory pipeline, "thinking" message |
| `onboarding.py` | FSM /start flow, user creation, timezone resolution |
| `subscription.py` | /subscribe, Telegram Stars pre_checkout_query, successful_payment |
| `habits.py` | /habits listing, /add_habit FSM, inline keyboard log callbacks |
| `settings.py` | /settings toggle, break mode, news digest toggle |
| `profile.py` | /profile display, account deletion confirmation |
| `multimodal.py` | Voice note STT, photo vision analysis |
| `group.py` | @mention detection, reply-to-bot detection, silent ignore |
| `triggers.py` | /triggers listing, /add_trigger FSM, max 5 limit |
| `userbot.py` | /connect_userbot MTProto auth flow, /disconnect_userbot cleanup |
| `admin.py` | Admin-only command gates |
| `oauth.py` | /connect_calendar OAuth flow |
| `break_mode.py` | /break mode activation/deactivation |
| `persona.py` | Persona selection |
| `gamification.py` | Gamification features |
| `story.py` | Story features |
| `memories.py` | Memory browsing |
| `referral.py` | Referral system |
| `common.py` | Unknown command fallback |

**Recommended approach:** Use `aiogram_tests` or manual mock-based handler tests. Start with `chat.py` (most critical path) and `subscription.py` (financial).

### 7. ProactiveFlows (`app/services/proactive_flows.py`)
**Risk Level: HIGH**
Zero test coverage. Orchestrates all autonomous interactions.

**Recommended tests:**
| Test name | Type |
|---|---|
| `test_run_flow_assembles_memory_and_calls_llm` | unit |
| `test_run_flow_sends_message_to_user` | unit |
| `test_run_flow_extracts_facts_after_response` | unit |
| `test_run_flow_redis_failure_doesnt_block_send` | unit |
| `test_morning_checkin_includes_streak_when_enabled` | unit |
| `test_news_digest_skips_when_no_articles` | unit |

### 8. ExtractorService (`app/services/extractor_service.py`)
**Risk Level: HIGH**
Zero test coverage for the memory extraction pipeline.

| What breaks | Impact |
|---|---|
| JSON parse failure from LLM | All fact extraction silently fails |
| Wrong importance classification | Facts stored in wrong memory tier |
| LLM API error | Silent failure, no facts extracted |

**Recommended tests:**
| Test name | Type |
|---|---|
| `test_find_write_info_core_fact_stored` | unit |
| `test_find_write_info_episode_stored` | unit |
| `test_find_write_info_working_stored` | unit |
| `test_find_write_info_malformed_json_returns_false` | unit |
| `test_find_write_info_no_facts_returns_false` | unit |
| `test_find_write_info_llm_error_returns_false` | unit |

### 9. UserBot Monitor (`app/services/userbot_monitor.py`)
**Risk Level: MEDIUM-HIGH**
Zero test coverage for Telethon event handlers.

| What breaks | Impact |
|---|---|
| Channel relevance classification wrong | Spam notifications or missed relevant posts |
| DM reply suggestions malformed | Embarrassing auto-replies if approved |
| Rate limiting bypassed | Notification flood |
| Style sample storage | Reply suggestions don't match user's tone |

**Recommended tests:**
| Test name | Type |
|---|---|
| `test_channel_post_relevant_sends_notification` | unit |
| `test_channel_post_irrelevant_skipped` | unit |
| `test_channel_notification_rate_limit` | unit |
| `test_dm_generates_reply_suggestions` | unit |
| `test_outgoing_message_stored_as_style_sample` | unit |

### 10. AccountService -- GDPR Deletion (`app/services/account_service.py`)
**Risk Level: HIGH**
Zero test coverage for account deletion.

| What breaks | Impact |
|---|---|
| Missing table in delete cascade | Orphaned data, GDPR violation |
| Delete order wrong (FK constraint) | Crash on deletion, user stuck |
| Export missing a table | Incomplete GDPR export |

**Recommended tests:**
| Test name | Type |
|---|---|
| `test_delete_user_removes_all_related_data` | integration |
| `test_delete_user_removes_scheduled_jobs` | unit |
| `test_export_user_data_includes_all_tables` | integration |
| `test_export_user_data_nonexistent_user` | unit |

### 11. ConversationHistoryService (`app/services/conversation_history_service.py`)
**Risk Level: MEDIUM**
Zero test coverage.

**Recommended tests:**
| Test name | Type |
|---|---|
| `test_save_and_get_history_round_trip` | unit |
| `test_history_trimmed_to_limit` | unit |
| `test_history_filters_non_text_messages` | unit |
| `test_empty_history_returns_empty_list` | unit |
| `test_malformed_json_in_redis_skipped` | unit |

### 12. SearchService (`app/services/search_service.py`)
**Risk Level: MEDIUM**
Zero test coverage.

**Recommended tests:**
| Test name | Type |
|---|---|
| `test_search_cache_hit` | unit |
| `test_search_cache_miss_calls_tavily` | unit |
| `test_search_no_api_key_returns_empty` | unit |
| `test_search_api_error_returns_empty` | unit |
| `test_check_rate_limit_admin_bypasses` | unit |
| `test_check_rate_limit_increments_counter` | unit |
| `test_format_results_for_llm_empty` | unit |
| `test_format_results_for_llm_with_dates` | unit |

### 13. Security -- Encryption Manager (`app/security/encryption_manager.py`)
**Risk Level: MEDIUM**
Only the `EncryptedTextType`/`EncryptedJSONType` type decorators are tested (via mocked encryptor). The actual Tink keyset initialization and `get_data_encryptor()` singleton are untested.

**Recommended tests:**
| Test name | Type |
|---|---|
| `test_encryption_manager_init_with_valid_keyset` | unit |
| `test_encryption_manager_init_with_invalid_keyset` | unit |
| `test_encrypted_text_type_handles_none` | unit |
| `test_encrypted_text_type_handles_legacy_plaintext` | unit |

### 14. Scheduler Jobs -- New Jobs Not Tested (`app/scheduler/jobs.py`)
**Risk Level: MEDIUM**
Several recently added jobs have no tests.

| Untested job | What it does |
|---|---|
| `news_digest_job` | Delivers personalised news |
| `custom_trigger_job` | Fires user-defined triggers |
| `channel_batch_flush_job` | Flushes channel post batches |
| `memory_reveal_job` | Progressive memory reveal |
| `insight_job` | Generates insight cards |
| `premium_taste_job` | Sends conversion prompts |
| `memory_decay_warning_job` | Warns about decaying memories |
| `archive_raw_conversations_job` | Archives Redis history to episodes |

**Recommended tests:** At minimum, test that each job handles missing user, break mode, and basic happy path.

---

## Test Infrastructure Issues

### 1. No Shared Fixtures or Factories
Every test file creates its own `FakeUser`, `FakeSession`, `FakeCore`, etc. This leads to:
- Massive duplication (the `FakeUser` class is defined at least 4 different ways)
- Inconsistent mock behavior across tests
- High maintenance cost when models change

**Recommendation:** Create a `tests/factories.py` with reusable fake object factories and a `tests/conftest.py` with shared pytest fixtures for mock sessions, users, and settings.

### 2. No Integration Tests Against a Real Database
All tests use mocked sessions. This means:
- SQLAlchemy query construction is never actually validated
- FK constraints, indexes, and triggers are never tested
- The pgvector similarity queries are never run against real data

**Recommendation:** Add a `tests/integration/` directory with a test PostgreSQL database (use `testcontainers` or a Docker Compose test profile) for critical paths: memory storage/retrieval, account deletion cascade, subscription quota.

### 3. No Async Test Runner Configuration
Tests use `asyncio.run()` to execute async code inline instead of using `pytest-asyncio`. This:
- Creates a new event loop per call (slower, different behavior than production)
- Makes it harder to share async fixtures

**Recommendation:** Add `pytest-asyncio` to dev dependencies and use `@pytest.mark.asyncio` decorators.

### 4. Potential Flaky Tests
| Test | Flakiness source |
|---|---|
| `test_scheduler_job_runs_async` | 10-second timeout waiting for APScheduler job fire; timing-sensitive |
| `test_schedule_list_and_cancel_reminder` | Uses real datetime math that could fail around midnight |
| All scheduler tests | Depend on `pytz` global scheduler state that leaks between tests |

### 5. No Mocks for External Dependencies
The codebase calls these external services but no test infrastructure exists to mock them:
- OpenRouter LLM API (`async_client`)
- Tavily Search API
- Google Calendar API
- Telethon MTProto
- Docker daemon
- Redis

---

## Priority Ranking for New Tests

| Priority | Module | Justification |
|---|---|---|
| P0 | `ConversationService.respond_with_tools` | Core business logic, touches every user interaction |
| P0 | `ToolExecutor` (all handlers) | Execute arbitrary actions on behalf of users |
| P0 | `SubscriptionService` | Financial logic, rate limiting |
| P1 | `CodeExecutorService._build_docker_cmd` | Security-critical (sandbox flags) |
| P1 | `CodeExecutorService._collect_output_files` | Security-critical (path traversal) |
| P1 | `HabitService._calculate_daily_streak` / `_calculate_weekly_streak` | Pure functions, easy to test, high user impact |
| P1 | `AccountService.delete_user_account` | GDPR compliance |
| P1 | `ExtractorService.find_write_important_info` | Memory pipeline correctness |
| P2 | `ProactiveFlows._run_flow` | Autonomous messages to users |
| P2 | Bot routers (chat.py, subscription.py) | User-facing command handlers |
| P2 | `SearchService` | Caching correctness, rate limiting |
| P2 | `ConversationHistoryService` | Data integrity of context window |
| P3 | `UserBotMonitor` | Complex but fewer users affected |
| P3 | Remaining scheduler jobs | Lower frequency, less complex |
| P3 | Test infrastructure (fixtures, factories) | Enables all other testing |

---

## Summary

The test suite covers approximately 5-8% of the codebase's critical paths. The existing tests are functional but suffer from heavy mock duplication, no shared infrastructure, and gaps around edge cases. The most urgent gaps are in the ReAct loop, tool execution pipeline, subscription logic, and security-critical code execution service. Adding even the P0 tests listed above would dramatically reduce the risk of regressions and silent failures in production.
