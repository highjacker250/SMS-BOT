---
name: code-review-findings
description: Comprehensive code review findings and improvement plan
metadata:
  type: project
---

## Critical Issues Found

### 1. **Security Vulnerabilities**
- **Hardcoded secrets in config.py** - `TG_API_ID` has a default value (39458429) that should be environment-only
- **No input validation/sanitization** on user-provided URLs, phone numbers, OTPs
- **SQL injection risk** - Not directly applicable (Supabase), but no parameterized query patterns
- **Session fixation** - In-memory storage with no rotation
- **Missing rate limiting** on API endpoints (`/api/health`, `/api/get_accounts`, etc.)

### 2. **Error Handling & Resilience**
- **Silent failures** - Many `except: pass` blocks swallow critical errors
- **No retry logic** for external API calls (Firebase, Telegram, AI APIs)
- **Cascading failures** - One scanner error can break entire loop
- **No circuit breaker** for external services
- **Database connection pooling** missing - creates new Supabase client per operation

### 3. **Code Quality & Architecture**
- **Massive functions** - `main.py` has 275 lines, `get_number.py` has 400+ lines
- **God objects** - `database.py` handles caching, saving, loading, activity feed, status
- **Tight coupling** - Handlers directly import `database`, `firebase_utils`, `config`
- **Duplicate code** - `get_number.py` and `whatsapp_scanner` both fetch clients
- **No type hints** - Makes refactoring risky
- **Magic numbers/strings** scattered throughout (timeouts, limits, status strings)

### 4. **Performance Issues**
- **N+1 queries** - Multiple `db.load_data()` calls in loops
- **No connection pooling** - New aiohttp session per request
- **Blocking operations** - `json.loads()` on large payloads in async context
- **Inefficient polling** - Multiple scanners with overlapping responsibilities
- **Memory leaks** - `USER_LOGIN_CLIENTS` dict never cleaned up

### 5. **Missing Features**
- **No structured logging** - Uses basic `logging` without JSON format
- **No health checks** - `/api/health` only returns bot status, not dependency health
- **No metrics/monitoring** - No Prometheus, OpenTelemetry
- **No graceful shutdown** - Tasks cancelled abruptly on exit
- **No tests** - Zero test coverage

---

## Improvement Priority Order

### Phase 1: Critical Security & Stability (Week 1)
1. Fix hardcoded defaults, add input validation
2. Add retry logic with exponential backoff for external calls
3. Fix silent exception handling
4. Add rate limiting on API endpoints
5. Fix memory leak in `USER_LOGIN_CLIENTS`

### Phase 2: Architecture & Code Quality (Week 2)
1. Extract service layer (Repository pattern for DB)
2. Add type hints across codebase
3. Split massive functions into smaller units
4. Add constants module for magic values
5. Implement connection pooling

### Phase 3: Observability & Resilience (Week 3)
1. Structured logging with correlation IDs
2. Health check endpoints for all dependencies
3. Circuit breaker for external services
4. Graceful shutdown with task cancellation
5. Basic metrics (counters, histograms)

### Phase 4: Testing & Documentation (Week 4)
1. Unit tests for critical paths
2. Integration tests for API endpoints
3. API documentation (OpenAPI/Swagger)
4. Load testing scripts

---

## Files Requiring Immediate Attention

| File | Priority | Issues |
|------|----------|--------|
| `main.py` | CRITICAL | Massive lifespan, no graceful shutdown, hardcoded ports |
| `database.py` | HIGH | No connection pooling, cache invalidation issues, silent errors |
| `core/scanner.py` | HIGH | Three overlapping scanners, N+1 queries, no retry |
| `firebase_utils.py` | HIGH | No timeout config, no retry, blocking json.loads |
| `services/telegram_automation.py` | HIGH | Memory leak, no proxy rotation logic, hardcoded delays |
| `services/proxy_manager.py` | MEDIUM | No proxy health scoring, single check endpoint |
| `services/ai_brain.py` | MEDIUM | No request timeout, sequential fallback |
| `handlers/user/get_number.py` | HIGH | 400+ lines, duplicate logic, blocking sleeps |
| `web_panel/templates/index.html` | MEDIUM | Inline JS, no CSP, large bundle |

---

## Quick Wins (Can Do Today)

1. **Add `pyproject.toml`** with ruff, mypy, pytest config
2. **Create `constants.py`** for all magic values
3. **Add `retry.py`** utility with exponential backoff
4. **Fix `config.py`** - remove hardcoded TG_API_ID default
5. **Add input validation** in all handler entry points
6. **Replace `except: pass`** with proper logging
7. **Add `AsyncExitStack`** for resource cleanup in scanners
8. **Implement cache TTL** in database.py instead of infinite cache