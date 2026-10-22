#!/usr/bin/env bash
set -e

# ==============================================================================
# Master Verification Script: SuperDocs Replit Workspace Document Panel
# ==============================================================================

BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
CYAN="\033[0;36m"
RED="\033[0;31m"
NC="\033[0m"

echo -e "${BLUE}${BOLD}====================================================================${NC}"
echo -e "${CYAN}${BOLD}   SUPERDOCS REPLIT WORKSPACE DOCUMENT PANEL — MASTER VERIFICATION  ${NC}"
echo -e "${BLUE}${BOLD}====================================================================${NC}"
echo ""

# 1. Typecheck
echo -e "${BOLD}[1/4] Running TypeScript Strict Typecheck...${NC}"
npx tsc --noEmit
echo -e "${GREEN}✓ TypeScript Typecheck Passed (Zero Type Errors)${NC}\n"

# 2. Unit & Integration Tests
echo -e "${BOLD}[2/4] Executing Vitest Unit & Integration Suite...${NC}"
npm run test
echo -e "${GREEN}✓ All Vitest Unit Tests Passed Successfully${NC}\n"

# 3. Playwright E2E Tests
echo -e "${BOLD}[3/4] Running Playwright End-to-End Test Suite...${NC}"
npm run test:e2e
echo -e "${GREEN}✓ All Playwright E2E Flows Passed Successfully${NC}\n"

# 4. Production Build
echo -e "${BOLD}[4/4] Generating Production Vite Bundle...${NC}"
npm run build
echo -e "${GREEN}✓ Production Bundle Compiled Successfully${NC}\n"

echo -e "${BLUE}${BOLD}====================================================================${NC}"
echo -e "${GREEN}${BOLD}   🎉 ALL 4 MASTER VERIFICATION GATES PASSED (100% GREEN)           ${NC}"
echo -e "${BLUE}${BOLD}====================================================================${NC}"
