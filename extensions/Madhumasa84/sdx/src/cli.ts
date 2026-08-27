#!/usr/bin/env node
import { installEarlyInterruptLatch } from './core/interrupt.js';

const removeEarlyInterruptLatch = installEarlyInterruptLatch();
try { await import('./program.js'); }
finally { removeEarlyInterruptLatch(); }
