# Changelog

## [Unreleased] — Gamification & Behavioral Design System

### Added

#### Gamification Core
- **XP & Leveling Engine** (F001): Event-driven XP awards with anti-abuse daily caps via Redis. Levels: Beginner → Planner → Strategist → Master → Sage. Commands: `/level`.
- **Badge/Achievement Engine** (F003): Data-driven badges with progress tracking. 11 predefined badges across action, milestone, social, and secret categories. Auto-unlocks with celebration messages. Command: `/badges`.
- **Variable Reward System** (F004): Mystery box mechanic triggered on milestones. Configurable probability tables (Common 60% / Rare 30% / Epic 10%) with pity timer guarantee after 10 consecutive commons. Full audit log.
- **Leaderboard Engine** (F005): Redis sorted sets for O(log N) ranking. All-time, weekly, and monthly windows. Privacy opt-out via settings. Command: `/leaderboard`.

#### Retention Mechanics
- **Conversation Streaks** (F006): Timezone-aware daily streak tracking. Freeze tokens awarded every 7 days (max 2). Streak milestones at 7, 30, 100, 365 days. Display in morning check-ins and `/level`.
- **Memory Milestone Celebrations** (F007): Celebratory messages at 10, 50, 100, 500, 1000 memories with sample facts included.
- **Progressive Memory Reveal** (F009): Scheduled messages at day 3 and day 7 showing what Motivi has learned, inviting corrections.
- **Break Mode Enhancement** (F011): Streak protection during breaks, empathetic activation message, personalized welcome-back on return.
- **Memory Decay Warning** (F028): Gentle notification when working memory entries approach decay.

#### Proactive Flow Enhancements
- **Onboarding Quick Win** (F008): Immediate "top 3 priorities" suggestion within 90 seconds of completing onboarding.
- **Motivi Knows Insight Cards** (F013): 2-3x/week LLM-generated pattern observations at semi-random times.
- **Adaptive Morning Tone** (F014): Evening mood extraction feeds next morning's tone (empathetic after hard days, energetic after wins).
- **Morning Challenge Cards** (F015): ~40% chance of including a personalized micro-challenge in morning check-ins.
- **Premium Feature Taste** (F019): Trial day 5 conversion prompt with actual usage statistics.

#### New Commands & Features
- **Contextual Upgrade Prompts** (F010): Rate-limit errors now show specific value propositions instead of generic messages.
- **Referral System** (F018): `/referral` generates shareable deep-link. Referrer gets 7 bonus days, friend gets 14-day trial.
- **Life Story** (F020): `/story` generates a narrative summary of the user's journey (unlocks after 30 days).
- **Memory Collection** (F025): `/my_memories` shows categorized memory counts.
- **Teach Motivi** (F029): `/correct` lets users review and delete incorrect core facts.
- **Persona Customization** (F026): System prompt modifier based on user tone/emoji/length preferences.
- **Easter Egg Responses** (F027): 1-in-50 chance of surprise elements (quotes, fun facts, challenges).

#### Infrastructure
- **Event Bus** (F002): Async in-process pub/sub for domain events. All gamification systems subscribe here.
- **Analytics Service**: Persists every domain event to `gamification_events` table for audit and reporting.
- **Feature Flags**: All 29 features gated behind flags, defaulting to false (dark launch). Configurable via `FEATURE_FLAGS_JSON` env var.

### Database
- New tables: `user_xp`, `user_badges`, `gamification_events`, `reward_logs`, `user_skill_xp`, `user_quests`, `accountability_pacts`, `circles`, `circle_members`
- New columns on `users`: `streak_count`, `streak_freeze_tokens`, `last_active_date`, `referral_code`, `referred_by`, `last_memory_milestone`
- New columns on `user_settings`: `show_on_leaderboard`, `hide_streak`, `persona_preferences_json`
- New column on `core_facts`: `category`
- Migration: `20260310_add_gamification_system`

### Routers
- `gamification` — `/level`, `/badges`, `/leaderboard`
- `referral` — `/referral`
- `story` — `/story`
- `memories` — `/my_memories`, `/correct`
