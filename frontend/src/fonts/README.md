# Self-hosted web fonts

Three variable WOFF2 families, Latin subset, are bundled for deterministic
frontend builds without a Google Fonts build-time network dependency.

Each file is the full variable weight axis, so the discrete weights the call
sites used to request are still available — `next/font/local` declares the range
in `weight` and the browser instances it.

| File                                      | Family              | Axis shipped                                |
| ----------------------------------------- | ------------------- | ------------------------------------------- |
| `Manrope-Variable-latin.woff2`            | Manrope             | `wght` 200–800                              |
| `PlusJakartaSans-Variable-latin.woff2`    | Plus Jakarta Sans   | `wght` 200–800                              |
| `JetBrainsMono-Variable-latin.woff2`      | JetBrains Mono      | `wght` 100–800                              |

Each font retains SIL Open Font License 1.1 independently of any project license.
The accompanying Manrope-OFL.txt, PlusJakartaSans-OFL.txt and JetBrainsMono-OFL.txt
contain the upstream copyright and full license. Source URLs and content digests
are recorded in licenses.json; do not remove these notices when distributing fonts.

To refresh a file, request its CSS with a modern Chrome user agent and take the
URL from the `/* latin */` block:

    curl -A '<modern Chrome UA>' \
      'https://fonts.googleapis.com/css2?family=Manrope:wght@200..800&display=swap'
