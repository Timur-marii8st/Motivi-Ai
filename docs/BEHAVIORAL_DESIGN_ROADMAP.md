# Motivi AI — Behavioral Design & Feature Roadmap

## 1. Product DNA Summary

### Core Value Proposition

Motivi transforms the chaotic inner monologue of productivity anxiety into an externalized, structured dialogue with an AI that *remembers you*. The transformation is: **from "I should be doing something but I don't know what" to "I know exactly what matters today and someone is watching out for me."**

The product's moat is not the LLM — it's the **memory layer**. Three-tier cognitive memory (Core + Working + Episodic) means Motivi becomes more valuable with every interaction. This is rare: most AI chatbots are stateless. Motivi accumulates context, which creates both utility and emotional attachment.

### Primary User Persona

**"Anxious Achiever"** — 22-35 year old knowledge worker or student (Russian-speaking primary, English secondary) who:
- **Goals**: Wants to be productive, build habits, feel in control of their time
- **Frustrations**: Calendar apps feel cold; habit trackers are abandoned after 2 weeks; existing AI assistants forget everything
- **Context of use**: Telegram (already open all day), quick check-ins between tasks, morning/evening rituals
- **Emotional state during use**: Ranges from morning optimism to evening guilt — the product must navigate both

### Current Engagement Loop

```
Onboarding (/start) → Set profile → Morning check-in (push)
    → Natural conversation throughout day (pull)
    → Habit logging via inline buttons (pull)
    → Evening wrap-up (push)
    → [Weekly/Monthly reviews] (push)
```

The loop has **two engines**: proactive flows (push, scheduled) and conversational interaction (pull, user-initiated). This is architecturally strong — most products have only one engine.

### What "Winning" Looks Like for the User

The user wins when they feel **seen and organized**. The "aha moment" is when Motivi references something the user said weeks ago in a contextually relevant way — proving the memory works. The second aha moment is receiving a morning message that accurately reflects their current priorities without them having to re-explain.

---

## 2. Psychological Lever Audit

| Lever | Currently Exploited? | Current Implementation | Untapped Potential |
|---|---|---|---|
| Progress & Mastery | Partially | Habit streaks exist but not surfaced prominently | No progress visualization, no level system, no milestone celebrations |
| Social Validation | Not at all | Zero social features | No sharing, no social proof, no leaderboards |
| Ownership & Investment | Strong | Memory accumulates; profile customization | Not explicitly surfaced to user ("you have 347 memories") |
| Variable Rewards | Weak | News digest has variability | No surprise elements, no discovery mechanics |
| Autonomy & Control | Strong | Custom triggers, settings toggles, skip tokens | Could be stronger with more persona customization |
| Identity & Belonging | Not at all | No community, no identity framing | No "type of user" classification, no tribe |
| Streaks & Commitments | Partial | Habit streaks exist | No conversation streaks, no commitment devices, streak protection missing |
| Scarcity & Urgency | Minimal | Trial is 7 days (implicit scarcity) | No feature-gating psychology, no FOMO |
| Novelty & Surprise | Weak | News digest is somewhat novel | No Easter eggs, no achievement unlocks, no persona evolution |
| Meaning & Narrative | Weak | System prompt has "warm personality" | No hero journey framing, no life narrative construction |

---

## 3. Feature List (18 Features)

---

### 3.1 Memory Milestone Celebrations
**Category**: Retention / Gamification
**Psychological Mechanism**: Endowed Progress Effect (Nunes & Dreze, 2006) — people who see evidence of progress already made are more likely to continue. Combined with Peak-End Rule (Kahneman) — memorable positive moments anchor emotional memory of the product.
**How it works**: Track memory count milestones (10, 50, 100, 500 facts/episodes). When a user crosses a threshold, Motivi sends a celebratory message: "I now know 100 things about you — like the fact that you prefer morning workouts and you're learning Rust. We've built something meaningful together." This makes the invisible investment visible.
**Implementation complexity**: Low — add counter queries in `core_memory_service.py` and `episodic_memory_service.py`, trigger check after each `extractor_service.find_write_important_info()` call in `chat.py`.
**Expected impact on**: D30 Retention (high), D1 Retention (low)
**Dark pattern risk**: None — purely celebratory, no guilt mechanics
**Inspired by**: Spotify Wrapped (making invisible usage data emotionally resonant)

---

### 3.2 Conversation Streak with Freeze Tokens
**Category**: Retention / Gamification
**Psychological Mechanism**: Loss Aversion (Kahneman & Tversky) — losing a streak hurts 2x more than gaining one feels good. Streak Freeze (borrowed from Duolingo) mitigates rage-quit risk by converting absolute loss into manageable grace.
**How it works**: Track consecutive days the user sends at least one message. Display streak count in morning check-ins. Award 1 "freeze token" per 7-day streak (max 2 stored). If a user misses a day but has a freeze token, the streak survives. This prevents the devastating moment where a 30-day streak breaks and the user never comes back.
**Implementation complexity**: Medium — add `streak_count`, `streak_freeze_tokens`, `last_active_date` to User model. Check/update in `handle_chat()`. Add migration.
**Expected impact on**: D7 Retention (very high), D30 Retention (high)
**Dark pattern risk**: Medium — streaks can create anxiety. **Mitigation**: Cap streak display, never use guilt language ("You missed a day!" is forbidden — instead "Welcome back! Your streak freeze kicked in"). Allow users to hide streak in /settings.
**Inspired by**: Duolingo (streak + freeze mechanic is their #1 retention driver)

---

### 3.3 Weekly Reflection Scorecard (Shareable Artifact)
**Category**: Virality / Retention
**Psychological Mechanism**: Self-Perception Theory (Bem, 1972) — people infer their attitudes from observing their own behavior. A visual scorecard makes the user *see* themselves as productive. Also exploits Social Currency (Berger, "Contagious") — people share things that make them look good.
**How it works**: Every Sunday (after weekly review), generate a visual scorecard image via the existing `execute_code` sandbox (matplotlib). Include: habits completed ratio, streak count, top 3 accomplishments (from episodic memory), a "productivity score" (0-100). The image is designed to be screenshot-friendly for Instagram/Telegram stories. Include a subtle "Powered by Motivi" watermark.
**Implementation complexity**: Medium — add a matplotlib template in sandbox, trigger from `weekly_plan_job`, use existing file output pipeline to send image.
**Expected impact on**: Virality (high), D30 Retention (medium)
**Dark pattern risk**: Low — opt-in sharing. Score should emphasize personal progress, not absolute performance.
**Inspired by**: Strava's year-in-review, Apple Watch activity rings sharing

---

### 3.4 Onboarding "Quick Win" — First Plan in 60 Seconds
**Category**: Onboarding / Activation
**Psychological Mechanism**: Zeigarnik Effect — people remember uncompleted tasks better than completed ones. Starting a plan creates an open loop. Also: Time-to-Value compression (Product-Led Growth principle) — the faster users experience core value, the higher activation.
**How it works**: After onboarding completes, instead of the current static summary, immediately trigger a mini morning check-in: "Now that I know you, let me suggest your top 3 priorities for today." This forces the first LLM-powered interaction within 90 seconds of signup, demonstrating the memory-powered value prop immediately. The plan creates an open loop ("Did I do those 3 things?") that pulls the user back for evening wrap-up.
**Implementation complexity**: Low — modify `finalize_onboarding()` in `onboarding.py` to call a lightweight version of `ProactiveFlows._run_flow()`.
**Expected impact on**: Activation (very high), D1 Retention (high)
**Dark pattern risk**: None
**Inspired by**: Notion's template gallery on first load, ChatGPT's suggested prompts

---

### 3.5 "Motivi Knows" Insight Cards
**Category**: Retention / Variable Rewards
**Psychological Mechanism**: Variable Ratio Reinforcement Schedule (Skinner) — unpredictable rewards are more engaging than predictable ones. Also: Curiosity Gap (Loewenstein) — people are drawn to close information gaps about themselves.
**How it works**: Periodically (2-3x per week, randomized), Motivi proactively sends a short "insight" derived from pattern analysis of the user's core memory and episodes. Examples: "I've noticed you're most productive on Tuesdays and Wednesdays — your habit completion rate is 40% higher." or "You've mentioned feeling stressed about deadlines 3 times this month. Want to talk about time management strategies?" These arrive at semi-random times (not on a fixed schedule) to create anticipation.
**Implementation complexity**: Medium — new APScheduler job with jittered timing, new LLM prompt template that receives aggregated stats, add `insights` proactive flow type.
**Expected impact on**: D7 Retention (high), D30 Retention (very high)
**Dark pattern risk**: Low — insights are genuinely useful. Respect break mode and notification preferences.
**Inspired by**: Spotify's "Only You" personalized insights, Apple Health trends

---

### 3.6 Habit Stacking Suggestions
**Category**: Retention / Behavioral Design
**Psychological Mechanism**: Habit Stacking (James Clear, "Atomic Habits") — linking a new behavior to an existing cue dramatically increases adoption. Implementation Intentions (Gollwitzer) — "When X happens, I will do Y" format doubles follow-through.
**How it works**: When a user creates a new habit, Motivi checks their existing habits and daily patterns (from episodic memory) and suggests a stack: "You already meditate at 7:00 — want to stack 'journal for 5 min' right after?" The reminder for the new habit is automatically set to fire 5 minutes after the existing habit's reminder. This leverages existing behavioral momentum.
**Implementation complexity**: Low — add logic in `habit_reminder` step of HabitCreation FSM, query existing habits from `HabitService`.
**Expected impact on**: D30 Retention (high — habits that stick retain users)
**Dark pattern risk**: None — genuinely helpful behavioral science
**Inspired by**: Habitica's quest-chaining, Atomic Habits methodology

---

### 3.7 "Life Story" Narrative Summary
**Category**: Retention / Identity
**Psychological Mechanism**: Narrative Identity Theory (McAdams) — people construct identity through the stories they tell about themselves. The IKEA Effect (Norton et al.) — people value things they helped create. A co-authored life narrative creates deep emotional investment.
**How it works**: After 30 days of use, unlock a `/story` command that generates a narrative summary of the user's journey: goals set, habits formed, challenges overcome, growth areas. Uses the full episodic memory and core facts. Presented as a beautifully formatted "chapter" of their life story. Updates monthly. This makes the accumulated memory tangible and emotionally valuable — the switching cost becomes enormous because you'd lose your story.
**Implementation complexity**: Medium — new router, new LLM prompt, query all episodic memory with date ranges. Consider generating a PDF via sandbox for premium users.
**Expected impact on**: D30 Retention (very high), Revenue (premium feature candidate)
**Dark pattern risk**: Low — genuinely valuable self-reflection tool
**Inspired by**: Day One Journal's "On This Day", Facebook Memories

---

### 3.8 Referral with Memory Transfer Incentive
**Category**: Acquisition / Virality
**Psychological Mechanism**: Social Currency + Reciprocity (Cialdini) — giving a friend something valuable (extended trial) creates obligation to reciprocate. Network Effects — each referral increases the social proof of the product.
**How it works**: Each user gets a unique referral link (`/referral`). When a friend signs up via the link: (1) friend gets 14-day trial instead of 7, (2) referrer gets 7 bonus days added to their trial/subscription. The referral message is pre-crafted and shareable: "I've been using Motivi as my AI planning assistant for [X days]. It remembers everything about my goals and keeps me on track. Try it with an extended trial: [link]"
**Implementation complexity**: Medium — add `referred_by` to User model, referral code generation, deep-link handling in `/start`, subscription extension logic.
**Expected impact on**: Virality (high), Acquisition (high)
**Dark pattern risk**: Low — transparent value exchange
**Inspired by**: Dropbox referral program (the canonical example), Duolingo Super referral

---

### 3.9 Adaptive Morning Tone (Emotional Intelligence)
**Category**: Retention / Personalization
**Psychological Mechanism**: Emotional Contagion Theory (Hatfield) — people unconsciously adopt the emotional tone of those they interact with. Also: Self-Determination Theory (Deci & Ryan) — competence/relatedness needs. A bot that reads your emotional state feels like it *understands* you.
**How it works**: During evening wrap-up, the extractor service already parses the conversation. Add sentiment/energy classification to extraction: was today a high-energy win or a draining slog? Store as a `mood_signal` in working memory. The next morning's check-in adapts its tone: after a hard day, lead with empathy ("Yesterday was tough. Let's make today lighter — here's a manageable plan."). After a great day, lead with momentum ("You crushed it yesterday! Let's keep the streak going."). This is not shown to users explicitly — it just *feels* right.
**Implementation complexity**: Medium — add mood classification to `extractor_service`, store in working memory, modify morning check-in prompt in `proactive_flows.py` to include mood context.
**Expected impact on**: D7 Retention (high), D30 Retention (high)
**Dark pattern risk**: None — purely empathetic, no manipulation
**Inspired by**: Replika's emotional mirroring, Woebot's CBT-informed tone adaptation

---

### 3.10 "Accountability Pact" with Stakes
**Category**: Retention / Commitment Device
**Psychological Mechanism**: Commitment Devices (behavioral economics) — pre-committing to a penalty for failure increases follow-through by 2-3x (Ariely). Loss Aversion — the pain of losing something is stronger than the pleasure of gaining it.
**How it works**: Users can create a "pact" for any habit: "If I miss [habit] for 3 days in a row, Motivi will [consequence]." Consequences are self-selected and soft: (1) send a brutally honest accountability message, (2) temporarily change Motivi's personality to "strict coach mode" for 24h, (3) add a "failed pact" entry to the weekly scorecard. No real monetary stakes — this is Telegram, not stickK. The power is in the pre-commitment ritual itself.
**Implementation complexity**: Medium — add `pact` model (habit_id, consequence_type, threshold_days), check in habit reminder job, add consequence delivery logic.
**Expected impact on**: D30 Retention (high), Habit completion rates
**Dark pattern risk**: Medium — self-imposed stakes can cause anxiety. **Mitigation**: Require explicit opt-in with a confirmation step. Allow easy cancellation. Never use shame language — frame as "you asked me to hold you accountable."
**Inspired by**: stickK.com, Beeminder's commitment contracts

---

### 3.11 Premium Feature Taste (Scarcity-Driven Conversion)
**Category**: Monetization / Scarcity
**Psychological Mechanism**: Endowment Effect (Thaler) — people overvalue things they already possess. Scarcity Principle (Cialdini) — limited access increases perceived value. IKEA Effect compound — users who've tasted premium features and *used* them feel loss when they're taken away.
**How it works**: During the 7-day trial, all premium features are unlocked (50 code executions, 100 searches, news digest, userbot). On day 5, Motivi sends a message: "You've used code execution 12 times and web search 8 times this week. Your trial ends in 2 days — after that, these drop to 5 and 10 per day. Want to keep the full experience?" This makes the impending loss concrete and quantified.
**Implementation complexity**: Low — add a scheduled job that fires on trial_day=5, query Redis counters for actual usage stats, send targeted conversion message.
**Expected impact on**: Revenue (very high), Trial-to-paid conversion
**Dark pattern risk**: Medium — loss framing can feel manipulative. **Mitigation**: Be transparent about exact limits. Never block existing functionality suddenly. Give a clear, honest comparison. Include a "no thanks, I'm fine with the free tier" button.
**Inspired by**: Spotify's premium trial with "your playlist will have ads after Thursday", LinkedIn Premium free month

---

### 3.12 Morning Challenge Cards
**Category**: Gamification / Retention
**Psychological Mechanism**: Quest Mechanic (Octalysis CD2) — small, achievable challenges provide a sense of accomplishment. Flow State (Csikszentmihalyi) — optimal engagement occurs when challenge matches skill level. Variable content prevents habituation.
**How it works**: Morning check-ins occasionally include a micro-challenge drawn from the user's goals and habits: "Today's challenge: Complete your top priority before noon and tell me about it." Challenges are generated by the LLM using core memory context so they're always relevant. Completing a challenge (user reports back) awards a small visual badge in the weekly scorecard. This adds game-like structure to what is otherwise an open-ended conversation.
**Implementation complexity**: Low — modify the morning check-in prompt in `proactive_flows.py` to sometimes include a challenge directive. Track challenge completion via conversation analysis in extractor.
**Expected impact on**: D7 Retention (high), Engagement depth
**Dark pattern risk**: None — optional, intrinsically motivating
**Inspired by**: Apple Watch's "close your rings" daily challenges

---

### 3.13 "Time Capsule" Scheduled Messages
**Category**: Retention / Emotional Investment
**Psychological Mechanism**: Future Self-Continuity (Hershfield) — people who feel connected to their future self make better long-term decisions. Curiosity Gap — a message scheduled for the future creates an open loop. Zeigarnik Effect — the user will remember the pending capsule.
**How it works**: Users can tell Motivi: "Remind me in 3 months to check if I've finished the Rust course." But instead of a simple reminder, Motivi creates a "time capsule" that includes: the current context (what the user was working on, their mood, their goals at the time). When it fires, the message includes this historical context: "3 months ago, you were just starting Chapter 2 of the Rust book and feeling excited about systems programming. How's it going?" This creates a powerful emotional moment.
**Implementation complexity**: Low-Medium — extend the existing `schedule_reminder` tool to capture a snapshot of current working memory and recent episodes at creation time. Store snapshot in reminder job args.
**Expected impact on**: D30+ Retention (very high — creates future touchpoints), Emotional attachment
**Dark pattern risk**: None — genuinely meaningful feature
**Inspired by**: FutureMe.org, iOS time-lapse memories

---

### 3.14 Group Accountability Circles
**Category**: Acquisition / Social / Retention
**Psychological Mechanism**: Social Facilitation (Zajonc) — people perform better when observed. Köhler Motivation Gain — weaker members of a group increase effort to match stronger members. Social Identity Theory (Tajfel) — belonging to a group shapes self-concept.
**How it works**: Users can create a "circle" of 3-5 friends (via Telegram group where bot is added). The bot tracks each member's habit completion and conversation engagement. Weekly, it posts a group scorecard (anonymized options available): "This week: Alex completed 6/7 habits, Sam 5/7, Jordan 4/7. The group average is 5/7 — up from last week!" No individual shaming, only group celebration. Leverages existing `group.py` router infrastructure.
**Implementation complexity**: High — requires group-level state management, per-member tracking within groups, new models for circles.
**Expected impact on**: Acquisition (high — each circle adds 3-5 users), D30 Retention (very high)
**Dark pattern risk**: Medium — social comparison can be toxic. **Mitigation**: Opt-in only. Allow anonymous mode. Focus on group trends, not individual rankings. Allow leaving without friction.
**Inspired by**: Peloton leaderboards, Weight Watchers meetings, Strava clubs

---

### 3.15 Progressive Memory Reveal (Onboarding Hook)
**Category**: Onboarding / Ownership
**Psychological Mechanism**: Endowed Progress Effect — showing users they've already started builds momentum. Curiosity Gap — teasing what Motivi "knows" creates pull to interact more. Ikea Effect — the user co-created this knowledge.
**How it works**: After 3 days of use, Motivi sends: "I've learned 12 things about you so far. Here are 3: [fact 1], [fact 2], [fact 3]. Want to see more? Keep chatting with me and I'll learn even more about your goals." After 7 days: "I now know 34 things about you. Here's what I understand about your work style: [summary]. Am I getting it right?" This gamifies the memory accumulation and gives users agency to correct/validate.
**Implementation complexity**: Low — scheduled job at day 3 and day 7, query `CoreFact` count and sample, send via proactive flow.
**Expected impact on**: Activation (high), D7 Retention (very high), Memory accuracy
**Dark pattern risk**: Low — some users may find it creepy that the bot "knows things." **Mitigation**: Always frame as "here's what I've noted — is this right?" Give users a `/forget` command to delete specific facts.
**Inspired by**: Netflix's "Because you watched..." reveal, Spotify Wrapped progressive reveal format

---

### 3.16 Skill Tree Visualization
**Category**: Gamification / Mastery
**Psychological Mechanism**: Self-Determination Theory (Competence need) — visible mastery progression satisfies a core psychological need. Goal Gradient Effect (Hull) — people accelerate effort as they approach a goal.
**How it works**: Map the user's activities into a skill tree: productivity skills (planning, time management), habit skills (consistency, stacking), self-knowledge skills (journaling, reflection), and tool mastery (calendar integration, code execution, web search). Each "skill" levels up based on usage patterns. Display via `/skills_tree` as a text-based ASCII tree or generate an image via sandbox. "You're a Level 3 Planner (42/100 XP to Level 4) — create 8 more weekly plans to level up!"
**Implementation complexity**: Medium — define skill categories and XP rules, track in a new `user_skills` table, rendering logic.
**Expected impact on**: D30 Retention (high), Feature adoption (high — users will try features to level up)
**Dark pattern risk**: Low — transparently gamified, no deception
**Inspired by**: Duolingo's skill tree, GitHub's contribution graph, Stack Overflow badges

---

### 3.17 "Break Mode" as Self-Care (Not Churn Signal)
**Category**: Retention / Anti-Churn
**Psychological Mechanism**: Psychological Reactance (Brehm) — when people feel their freedom is threatened, they resist. Paradox of Choice — giving explicit permission to disengage reduces guilt and increases return rate. Autonomy (SDT) — honoring the user's need for space builds trust.
**How it works**: Currently, break mode simply pauses notifications. Enhance it: when a user activates break mode, Motivi says "Taking a break is healthy. I'll keep your streaks frozen and your memories safe. When you're ready, just say hi and I'll catch you up on everything you missed." When break ends, send a personalized "welcome back" with a summary of what happened while they were away (news, habit recommendations). This reframes absence as intentional self-care rather than abandonment.
**Implementation complexity**: Low — modify break mode activation/deactivation messages, add a "welcome back" proactive flow that triggers on first message after break, auto-apply streak freeze during break.
**Expected impact on**: Churn reduction (high — turns potential churners into returning users)
**Dark pattern risk**: None — explicitly anti-dark-pattern
**Inspired by**: Headspace's "it's okay to take a break" messaging, Calm's return experience

---

### 3.18 Contextual Upgrade Prompts (Not Paywalls)
**Category**: Monetization
**Psychological Mechanism**: Jobs-to-Be-Done (Christensen) — people "hire" products for specific jobs. Upgrade prompts are most effective at the exact moment the user encounters a limit while trying to accomplish a specific job. Pain of Paying (Prelec & Loewenstein) — reducing payment friction at the moment of highest motivation maximizes conversion.
**How it works**: Instead of generic "upgrade to premium" messages, trigger contextual prompts only when the user hits a real limit: "You've used all 5 code executions today. I was about to generate that Excel report for you — want to unlock 50 daily executions?" or "I found 3 great articles about Rust for your digest, but news digest is a premium feature. Want to try it?" Always show exactly what value they'd get in this specific moment.
**Implementation complexity**: Low — modify the rate-limit error messages in `tool_executor.py` to include contextual value propositions instead of generic limits.
**Expected impact on**: Revenue (very high), Conversion (high)
**Dark pattern risk**: Low — showing the blocked value is honest, not manipulative. Never fake urgency.
**Inspired by**: Canva's "upgrade to remove watermark" at export time, Grammarly's premium suggestions inline

---

## 4. Full Gamification System (Octalysis Framework)

### CD1: Epic Meaning & Calling
**Mechanic: "Personal Growth Quest"**
Frame the entire Motivi experience as a personal development journey. During onboarding, ask: "What's the one thing you want to achieve in the next 90 days?" This becomes the user's "quest." All morning check-ins, habit tracking, and weekly reviews are framed as progress toward this quest. Monthly review includes quest progress assessment. When the quest is completed, celebrate dramatically and prompt a new one.

**Mechanic: "Memory Guardian"**
Position Motivi not as a tool but as a guardian of the user's personal narrative. "I remember your goals so you can focus on achieving them." This elevates the product from utility to meaning.

### CD2: Development & Accomplishment
**Mechanic: "Productivity XP System"**
Award XP for: completing habits (10 XP), logging in daily (5 XP), creating plans (15 XP), completing challenges (25 XP), using new features (20 XP first time). Level thresholds: 0-100 (Beginner), 100-500 (Planner), 500-1500 (Strategist), 1500-5000 (Master), 5000+ (Sage). Level displayed in profile and morning greetings.

**Mechanic: "Achievement Badges"**
Unlock badges for specific behaviors: "Early Bird" (complete a task before 8 AM 5 times), "Streak Legend" (30-day conversation streak), "Memory Maker" (100 core facts stored), "Code Wizard" (use code execution 10 times). Each badge is a one-time unlock with a celebration message.

### CD3: Empowerment of Creativity & Feedback
**Mechanic: "Custom Trigger Mastery"**
The existing custom triggers feature already serves this drive. Enhance it: show users examples of creative trigger use cases during onboarding. "Power users create triggers like 'Sunday evening meal planning' or 'Friday gratitude reflection.'" Allow trigger templates that can be shared.

**Mechanic: "Teach Motivi"**
Add a `/correct` command that lets users explicitly correct Motivi's understanding. "Actually, I stopped working at Company X — I'm freelancing now." This gives users creative control over their AI's knowledge, satisfying the feedback loop.

### CD4: Ownership & Possession
**Mechanic: "Memory Collection"**
Present core facts as a "collection" the user builds over time. `/my_memories` shows categories: "Career (23 facts), Health (12 facts), Interests (18 facts), Goals (8 facts)." This transforms invisible data into a visible, ownable collection.

**Mechanic: "Persona Customization"**
Let premium users customize Motivi's communication style: formal/casual, emoji density, response length preference, preferred encouragement style. These settings become part of the user's investment in the product.

### CD5: Social Influence & Relatedness
**Mechanic: "Accountability Circles"** (described in Feature 3.14 above)

**Mechanic: "Anonymous Benchmark"**
"Users like you (same occupation, similar habits) average a 73% habit completion rate. You're at 81% — above average!" No identifying information shared, but social proof that the system works and the user is doing well.

### CD6: Scarcity & Impatience
**Mechanic: "Feature Unlocks by Usage"**
Gate advanced features behind engagement milestones rather than purely subscription: news digest unlocks after 7 days of consecutive use, custom triggers after creating 3 habits, code execution after 14 days. This creates anticipation and rewards engagement even for free users.

**Mechanic: "Limited Daily Insights"**
The "Motivi Knows" insight cards (Feature 3.5) arrive only 2-3 times per week, unpredictably. Users can't demand them — they appear when Motivi has something genuinely interesting to say. Scarcity of the insight makes each one more valued.

### CD7: Unpredictability & Curiosity
**Mechanic: "Easter Egg Responses"**
Occasionally (1 in 50 interactions), Motivi includes an unexpected element: a relevant quote, a fun fact related to the user's interests, a playful challenge. "Fun fact: since you started tracking your reading habit 23 days ago, you've read an estimated 460 pages. That's longer than The Great Gatsby!"

**Mechanic: "Mystery Challenge"**
Once per week, offer a sealed challenge: "I have a special challenge for you today. Accept it to find out what it is." The challenge is always achievable and personalized but the hidden nature creates a curiosity-driven pull.

### CD8: Loss & Avoidance
**Mechanic: "Streak Protection"** (described in Feature 3.2 above)

**Mechanic: "Memory Decay Warning"**
Working memory already decays after N days. Make this visible: "Some of your recent context is fading from my working memory. Chat with me today to keep it fresh." This is technically honest (working memory does decay) and creates a natural pull to interact. Gentle, not alarmist.

---

## 5. 90-Day Retention Architecture

### Day 0-1: Aha Moment Engineering

**Target**: User experiences memory-powered personalization within 90 seconds of completing onboarding.

| Touchpoint | Action | Psychological Hook |
|---|---|---|
| Minute 0 | /start — conversational onboarding (name, city, times, occupation) | Commitment & Consistency — answering personal questions creates investment |
| Minute 1.5 | Immediately after onboarding: "Based on what you told me, here are 3 priorities for today" | Time-to-Value compression — prove the product works *now* |
| Minute 2 | "I've saved your profile. I'll check in tomorrow at [wake_time]. Want to create your first habit?" | Open loop (Zeigarnik) — tomorrow's check-in creates anticipation |
| Hour 1 (if evening) | If onboarded after 6 PM: trigger a lightweight evening reflection instead of morning plan | Contextual relevance — don't suggest morning tasks at night |
| Hour ~12 | First proactive check-in (morning or evening depending on signup time) | Push notification as promised — builds trust in the system |

**Anti-pattern to avoid**: Do NOT send a tutorial or feature list. The user doesn't care about features — they care about "does this help me?" Show, don't tell.

### Day 2-7: Habit Formation Hooks

| Day | Push Touchpoint | Pull Trigger | Hook |
|---|---|---|---|
| 2 | Morning check-in with yesterday's context | Suggest first habit creation | Continuity — "yesterday you mentioned X" proves memory works |
| 3 | Progressive memory reveal: "I've learned 12 things about you" | Correct/validate facts | Endowed Progress — make investment visible |
| 4 | Morning challenge card | Habit reminder with inline button | Variable reward — challenges add novelty to routine |
| 5 | Trial countdown (if trial): honest usage stats + conversion prompt | Web search or code exec exposure | Loss aversion — quantify what they'd lose |
| 6 | "Motivi Knows" insight — first pattern observation | Habit stacking suggestion if 2+ habits exist | Curiosity — "it noticed something about me" |
| 7 | First weekly review + scorecard image | /referral prompt after positive weekly review | Social currency — share after positive experience |

**Key metric**: Measure "4-of-7 active days" — if the user interacts on 4+ of their first 7 days, D30 retention historically exceeds 60% for habit-forming products.

### Day 8-30: Investment Deepening

| Week | Strategy | Mechanics |
|---|---|---|
| Week 2 | Feature expansion | Introduce custom triggers, Google Calendar, news digest. Each new feature is another thread tying the user to the product. |
| Week 2-3 | Investment visibility | "You have 47 memories, 2 active habits, and a 12-day streak." Make switching cost tangible without guilt. |
| Week 3 | Accountability pact (optional) | Offer commitment devices for users who want more structure. This deepens engagement for power users. |
| Week 4 | Monthly review | First monthly plan generation — demonstrate long-term value. "Here's how your February went and what March could look like." |

**Switching cost escalation**: By day 30, the user has: (1) 50-100+ core facts stored, (2) habit history and streaks, (3) episodic memories, (4) custom triggers and plans, (5) potentially a connected calendar and userbot. Rebuilding this elsewhere is painful.

### Day 31-90: Identity Fusion

| Milestone | Action | Psychological Mechanism |
|---|---|---|
| Day 30 | Unlock `/story` — life narrative summary | Narrative Identity — "this is my story, co-authored with Motivi" |
| Day 45 | "You're a Level 3 Planner" — skill tree reveal | Mastery progression — identity as "someone who plans" |
| Day 60 | Accountability circle suggestion (if friends use it) | Social identity — "we are Motivi users" |
| Day 90 | "Quarter in Review" — comprehensive reflection + goal-setting for next quarter | Ritual — quarterly review becomes part of life rhythm |

**Identity markers**: The user should be able to say "I use Motivi to organize my life" as naturally as "I use Google Calendar." The product should feel like a *practice*, not a tool.

---

## 6. Viral Loop Design

### Loop 1: Content Loop (Shareable Artifacts)
```
User completes week → Weekly scorecard generated (image) →
User shares to Telegram/Instagram story → Friend sees "Powered by Motivi" →
Friend clicks link → Signs up with extended trial (referral)
```
**K-factor estimate**: If 10% of users share their scorecard and 5% of viewers convert, with an average of 200 story views: 0.1 x 0.05 x 200 = 1.0 (viral — each user brings 1 new user). Realistically, k=0.3-0.5 is achievable.

### Loop 2: Network Loop (Group Accountability)
```
User creates accountability circle → Invites 3-4 friends →
Friends must install bot to participate → Friends become individual users →
Friends create their own circles
```
**K-factor**: If 20% of users create circles with average 3 new members, and 50% of invited friends become active: 0.2 x 3 x 0.5 = 0.3.

### Loop 3: Referral Loop (Direct Incentive)
```
User hits positive moment (completed quest, streak milestone, great weekly review) →
Contextual referral prompt: "Share this feeling — invite a friend" →
Friend gets 14-day trial, user gets 7 bonus days →
Friend onboards
```
**Key insight**: Trigger referral prompts at emotional peaks (after celebration messages, not during neutral moments). Peak-state referrals convert 3-5x better.

### Loop 4: Status Loop (Implicit)
```
User mentions Motivi in conversation ("my AI assistant suggested...") →
Social curiosity → "What's Motivi?" → Organic discovery
```
This loop is untrackable but real. The "Life Story" and "Time Capsule" features create conversation-worthy moments that naturally lead to word-of-mouth.

---

## 7. Prioritized Top-10 Roadmap

Scoring: IMPACT (1-10) x FEASIBILITY (1-10) / ETHICAL_RISK (1-10, where 1=no risk, 10=high risk)

| Rank | Feature | Impact | Feasibility | Ethical Risk | Score | Priority |
|---|---|---|---|---|---|---|
| 1 | **Onboarding Quick Win** (3.4) | 9 | 9 | 1 | 81.0 | P0 — Ship this week |
| 2 | **Conversation Streak + Freeze** (3.2) | 9 | 7 | 3 | 21.0 | P0 — Ship in Sprint 1 |
| 3 | **Progressive Memory Reveal** (3.15) | 8 | 8 | 2 | 32.0 | P0 — Ship in Sprint 1 |
| 4 | **Memory Milestone Celebrations** (3.1) | 7 | 9 | 1 | 63.0 | P0 — Ship in Sprint 1 |
| 5 | **Contextual Upgrade Prompts** (3.18) | 9 | 8 | 2 | 36.0 | P1 — Sprint 2 |
| 6 | **Break Mode Enhancement** (3.17) | 7 | 9 | 1 | 63.0 | P1 — Sprint 2 |
| 7 | **Weekly Scorecard** (3.3) | 8 | 6 | 1 | 48.0 | P1 — Sprint 2 |
| 8 | **Motivi Knows Insights** (3.5) | 8 | 6 | 2 | 24.0 | P1 — Sprint 3 |
| 9 | **Adaptive Morning Tone** (3.9) | 7 | 6 | 1 | 42.0 | P2 — Sprint 3 |
| 10 | **Referral with Extended Trial** (3.8) | 8 | 5 | 1 | 40.0 | P2 — Sprint 3 |

**Rationale for ranking**: The top 4 are all low-complexity, high-impact retention plays that require minimal new infrastructure. They exploit the existing memory system (Motivi's moat) and focus on making invisible investment visible. Revenue optimization (contextual prompts) comes after retention is solid — there's no point optimizing conversion on a leaky bucket. Viral features (scorecard, referral) come in Sprint 2-3 once the retention flywheel is spinning.

**What a typical PM would miss**: The most impactful feature here is **not** the gamification (streaks, XP) — it's the **Progressive Memory Reveal** (3.15). Behavioral science shows that the single strongest predictor of retention in AI products is the user's belief that the AI *understands* them. Making the memory visible at day 3 and day 7 directly attacks the core retention question: "Is this AI actually learning about me?" Most PMs would prioritize flashy gamification; the contrarian bet is that showing the memory is more powerful than any game mechanic.

---

*Document generated for Motivi AI (commit: current HEAD on claude/add-claude-documentation-rf9Yg)*
*Frameworks referenced: Octalysis (Yu-kai Chou), Self-Determination Theory (Deci & Ryan), BJ Fogg Behavior Model, Hooked Model (Nir Eyal), Contagious (Jonah Berger), Thinking Fast and Slow (Kahneman)*
