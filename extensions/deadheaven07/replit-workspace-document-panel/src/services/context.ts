import { buildProjectContext } from './replit';

export interface GenerationContext {
  documentType: 'readme' | 'spec' | 'user-guide';
  instruction: string;
  projectContext: string;
  selectedPaths: string[];
}

export const DEFAULT_INSTRUCTIONS: Record<string, string> = {
  readme: `Generate a comprehensive README.md for this project. Include:
- Project title and description
- Features and capabilities
- Installation and setup instructions
- Usage examples
- Configuration options
- API documentation (if applicable)
- Contributing guidelines
- License information`,
  
  spec: `Generate a technical specification document for this project. Include:
- System overview and architecture
- Component/module breakdown
- Data models and schemas
- API endpoints and interfaces
- Configuration and environment
- Deployment requirements
- Testing strategy
- Security considerations`,
  
  'user-guide': `Generate a user-facing guide for this project. Include:
- Getting started tutorial
- Core concepts and terminology
- Step-by-step workflows
- Common use cases and examples
- Configuration guide
- Troubleshooting and FAQ
- Advanced features`,
};

export function createGenerationContext(
  documentType: 'readme' | 'spec' | 'user-guide',
  instruction: string,
  selectedFiles: Map<string, string>
): GenerationContext {
  const basePrompt = DEFAULT_INSTRUCTIONS[documentType] || DEFAULT_INSTRUCTIONS.readme;
  const { context: projectContext, skippedFiles } = buildProjectContext(selectedFiles, documentType);
  
  let finalInstruction = instruction.trim() || basePrompt;
  
  // If files were skipped due to size limit, prepend a warning to the instruction
  if (skippedFiles.length > 0) {
    const skippedList = skippedFiles.map(f => `\`${f.path}\``).join(', ');
    finalInstruction = `[WARNING: ${skippedFiles.length} file(s) skipped due to context size limit: ${skippedList}. The generated document may be incomplete.]\n\n${finalInstruction}`;
  }
  
  return {
    documentType,
    instruction: finalInstruction,
    projectContext,
    selectedPaths: Array.from(selectedFiles.keys()).sort(),
  };
}

export function buildSuperDocsInstruction(context: GenerationContext): string {
  return `${context.instruction}

---

## Project Context

${context.projectContext}

---

Please generate a ${context.documentType === 'readme' ? 'README.md' : context.documentType === 'spec' ? 'SPEC.md' : 'USER_GUIDE.md'} based on the above project context and instruction.`;
}