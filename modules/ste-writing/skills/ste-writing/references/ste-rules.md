# ASD-STE100 rules, and which ones the 80% keeps

ASD-STE100 (Simplified Technical English) is a controlled language for aircraft
maintenance documentation, maintained by the ASD STEMG. Issue 8 (2021) has 53
writing rules in nine sections plus a dictionary of about 900 approved words,
each with exactly one approved meaning. Agents already know the specification
well: naming it in one sentence moves prose most of the way. The notes below
say which rules the 80% keeps, which ones it drops, and why.

## Kept (the 80%)

| Rule family | What it says | Why it survives for agent prose |
|---|---|---|
| Sentence length | Instructions at most 20 words, descriptions at most 25 | The main readability lever. Treat the limit as a ceiling (see below). |
| One idea per sentence | One instruction per sentence in a procedure; one topic per descriptive sentence | Stops the subordinate-clause pileups that make a reader back up. |
| Active voice | Name the actor: "the client retries", not "requests are retried" | Says who does what, which is the question a reader of agent output usually has. |
| Verb forms | Simple present for descriptions, imperative for instructions, simple past for events | Removes tense drift inside one paragraph. |
| One word, one meaning | Use the same word for the same thing throughout; do not vary a term for style | Synonym variation ("cache", "store", "map") reads as three things. |
| Articles | Keep "a", "an", "the". No telegraphic style | Dropped articles save nothing and cost parsing. |
| Noun clusters | At most three nouns in a row; break longer ones with prepositions | "session token refresh handler path" is unreadable; "the path of the handler that refreshes the session token" is not. |
| Conditions first | "If X, do Y", never "Do Y if X" | The reader learns whether the step applies before reading the step. |
| Vertical lists | A sequence or set of more than two items becomes a list | Scannability. |
| Paragraphs | At most six sentences, the first stating the topic | A reader can skim topic sentences and stop. |
| Punctuation | Simple: no semicolons, few parentheses, no dashes used as commas | Each of those hides a second idea in the sentence. |

## Dropped (the 20%)

| Rule | Why it goes |
|---|---|
| The approved-word dictionary | Engineering prose needs its own nouns: `OrderedDict`, idempotency, checkpoint. Forcing approved synonyms makes the text less precise, not more. Technical names are allowed by the spec anyway; the 80% extends that to project vocabulary. |
| No -ing forms outside technical names | "retrying", "logging", "blocking" are the plain words; the workarounds ("the act of retry") read worse. |
| No connecting words between sentences in procedures | "because", "so", "which", "when" are how two fragments become one clear sentence. Over-splitting is the failure mode measured in testing. |

## The three corrections (added after measurement)

Tested across seven coding-agent writing tasks on two model tiers, every
variant of the instruction kept 97–100% of the source facts and every
command and identifier verbatim. The spec does not cost information. It costs
voice, in three specific ways that the skill body corrects:

1. **Ceiling treated as target.** Mean sentence length fell from ~12 words
   (no instruction) to ~8, with a 90th percentile of ~13. The judge's
   complaint in nearly every graded output: "choppy", "short subject-verb
   sentences", "repeats the subject". Hence: aim for 12–16, vary the length.
2. **Form overridden.** A Slack message grew bold section labels; a request
   for "a few paragraphs" came back as a report. Hence: the medium wins.
3. **Over-specification backfires.** A full rule list produced the lowest
   naturalness of any variant on both tiers, below the one-sentence "about 80%
   of the way to ASD-STE100". A later round confirmed it from the other side:
   a longer skill body with two extra sections scored 0.35 below the same text
   without them. The model knows the spec; it needs the relaxations and the
   corrections, not the rules restated.

One addition earned its place: naming the reader ("a tired engineer on a
phone between meetings, who must get every fact in one pass") raised the
scores on the larger tier and, combined with the spec anchor, held them on the
smaller one. The module README has the tables.

## Where it helps and where it does not

Good fits: procedures and runbooks, PR descriptions, status handoffs, bug
write-ups to be filed (not chatted), anything a reader scans rather than
reads. The scannability score rose in every one of these.

Poor fits: a conversational message to one person, teaching prose that needs
to carry a "why" across sentences, and any text whose format is already a
convention (commit bodies, docstrings, changelogs). Apply the style inside the
form or leave the form alone.
