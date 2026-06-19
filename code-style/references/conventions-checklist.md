# Conventions checklist

The lens for step 3: what to look for when learning a project's conventions from its own code. You don't check every item on every file — scan the changed code, then confirm each dimension that appears in it against 2–4 neighbor files. Evidence from neighbors always wins over anything here.

A convention only counts if the codebase is consistent about it. If neighbors disagree, follow the nearest/most-recent ones; if the whole repo is genuinely mixed on something, leave it alone rather than picking a side.

## Formatting (usually owned by a formatter — defer to it)
- Indentation: tabs vs spaces, width
- Quotes: single vs double; template literals vs concatenation
- Semicolons; trailing commas in multiline literals/params
- Max line length and how long lines are wrapped
- Brace style; spacing inside `{ }`, `[ ]`, before function parens
- Blank-line rhythm between members/blocks

If a formatter config exists, these are settled — run it instead of hand-editing.

## Naming
- Case per identifier kind: variables, functions, constants, classes/types, files, components
- Descriptiveness of variables AND function parameters: does the project allow terse `e`/`i`/`x`/`a`/`b`, or spell names out like `event`/`index`/`pointA`? If neighbors are consistently descriptive, rename terse names in the new code to match (renaming locals/params is behavior-safe). Keep terse names only where the project itself uses them (e.g. loop `i`, math `dx`).
- Booleans (`is`/`has`/`should` prefixes), handlers (`onX`/`handleX`), private members (`_x`?)
- Acronym casing (`URL` vs `Url`, `id` vs `Id`)
- File/dir naming (kebab vs camel vs Pascal), and how a file name relates to its main export

## Imports & module structure
- Grouping and order (external → internal → relative; alphabetized?)
- Path style: aliases (`@/…`, `~/…`) vs relative `../`
- Named vs default exports; one export per file vs barrels/index files
- `import type` / type-only imports; side-effect import placement
- Where a file puts constants, helpers, the main export, and exports (top vs bottom)

## Types (typed languages)
- Inference vs explicit annotations; where annotations are expected (params, returns, public API)
- `interface` vs `type`; enums vs unions vs const objects
- `any`/`unknown` tolerance; non-null assertions; generics naming
- Optional vs `| undefined`; nullability conventions

## Comments & docs
- Density: heavily commented vs near-none — match it; don't add narration to a terse codebase
- Doc style: JSDoc/TSDoc/docstrings — format, and which symbols get them
- Inline comment voice (terse vs full sentences), TODO/FIXME format
- **Preserve existing comments** when editing; don't strip them as part of a "style" pass

## Functions & control flow idioms
- Declaration style: `function` vs arrow; arrow-param parens (`x =>` vs `(x) =>`)
- Early-return/guard-clause vs nested conditionals
- Loops vs array methods (`map`/`filter`/`reduce`); `for…of` vs `forEach`
- async/await vs `.then`; how errors are caught and surfaced
- Equality/quote/spread idioms the repo clearly favors (e.g. keeping `!!x` coercions)

## Errors, logging, returns
Only when the changed code already does these — match the surface, never change control flow or error/return *semantics* for style:
- How errors are thrown/wrapped/typed; custom error classes
- Logging channel and format (logger vs `console`); log levels
- Return shape conventions (result objects, early returns, null vs throw)

## Language / framework idioms
Match how *this* project uses its stack, from neighbors:
- React/Vue: component shape, props/emits declaration, hooks/composables order, file layout, event-handler naming, template attribute conventions
- Backend handlers: controller/service/route split, validation placement, response helpers
- State/data: store action patterns, fetch/query wrappers, DTO/serialization shape
- i18n, feature flags, sanitization, or other cross-cutting helpers the repo wraps (use the wrapper, don't bypass it)

## Tests
- File location & naming (`__tests__/x.spec.js`, `x.test.ts`, sibling vs mirrored dir)
- Framework idioms: `describe` blocks vs flat tests; global vs imported assertions
- Naming of test cases, fixture/mock/setup patterns, assertion style
