# Lessons

One dated entry per delivery unit (design requirement LESSON-1). Format: date, unit, what happened, what to do
differently. Newest first.

## 2026-10-11, U1 repository skeleton

- Scaffold defaults must not claim checks that do not exist: the README lists install channels as planned and
  names the one area that ships, so the front page cannot get ahead of the code.
- A dispatcher that imports every area module must treat one broken module as a warning, never a crash; the
  parallel units add areas independently and one bad import must not take the CLI down.
- A guard script must not exempt itself: build fixtures from code points and string pieces so the script scans
  its own source and tests with the same rules as everything else.
