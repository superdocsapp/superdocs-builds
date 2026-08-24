\# TipTap SuperDocs



A thin TipTap extension for SuperDocs AI editing.



\## Architecture



The package has a framework-independent ProseMirror core and a thin

TipTap adapter.



```text

&#x20;                SuperDocs Core

&#x20;               ProseMirror Plugin

&#x20;                      |

&#x20;             +--------+--------+

&#x20;             |                 |

&#x20;           TipTap          BlockNote

&#x20;           adapter          example

