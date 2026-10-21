/** A small manuscript that exercises every feature the compiler claims. */

import { MemoryVault } from "../helpers";

export const SPINE = `---
title: A Small Book
author: T. Tester
bibliography: refs.bib
---

## Front Matter

- [[Front/Preface]]

## Part One

1. [[Ch/One]]
2. [[Ch/Two]]

## Back Matter

- [[Back/Colophon]]
`;

export const BIB = `
@book{alpha2001,
  author = {Alpha, Ada},
  title = {The First Book},
  year = {2001},
  publisher = {Press One},
}
@article{beta1999,
  author = {Beta, Bo and Gamma, Gus},
  title = {On Second Things},
  journal = {Journal of Things},
  volume = {4},
  pages = {1--10},
  year = {1999},
}
@book{never2020,
  author = {Never, Nan},
  title = {Never Cited},
  year = {2020},
  publisher = {Press Two},
}
`;

export function smallVault(): MemoryVault {
  const vault = new MemoryVault({
    "Manuscript.md": SPINE,
    "refs.bib": BIB,
    "Front/Preface.md": `# Preface\n\nA short preface.\n`,
    "Ch/One.md": `# Chapter One

Opening line with a citation [@alpha2001, p. 3].

![[img/first.png|The first plate.]]

Some prose with an inline note.^[An inline note, citing [@beta1999].]

### A deep heading

Text under it.

See [[img/second.png]] for the other plate, and [[Ch/Two]] for more.
`,
    "Ch/Two.md": `# Chapter Two

More prose[^ref].

![[img/second.png|The second plate.]]

[^ref]: A reference-form note that cites [@beta1999].
`,
    "Back/Colophon.md": `# Colophon\n\nSet in nothing in particular.\n`,
  });
  vault.setBinary("img/first.png", new Uint8Array([1, 2, 3, 4]));
  vault.setBinary("img/second.png", new Uint8Array([5, 6, 7, 8]));
  return vault;
}
