import { describe, it, expect, vi } from 'vitest';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { TemplateGallery, injectVariables } from '../src/components/TemplateGallery';
import { Template, Prompt } from '../src/types/superdocs';

// @ts-expect-error configure React 18 act testing environment
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe('TemplateGallery Component & Variable Injection', () => {
  const mockTemplates: Template[] = [
    {
      id: 'tmpl_readme_pro',
      name: 'Professional README',
      description: 'Standard enterprise README template',
      document_type: 'readme',
      variables: [
        { name: 'project_name', description: 'Name of the project', required: true, default_value: 'My App' },
        { name: 'author', description: 'Author name', required: false, default_value: 'Dev Team' },
      ],
      default_content: '# {{project_name}}\n\nCreated by {{author}}.',
    },
  ];

  const mockPrompts: Prompt[] = [
    {
      id: 'prompt_api_docs',
      name: 'API Reference Focus',
      description: 'Focus on OpenAPI endpoints and authentication',
      template: 'Document all endpoints in {{module}} with strict type contracts.',
      variables: [
        { name: 'module', description: 'Target module name', required: true, default_value: 'auth' },
      ],
    },
  ];

  it('correctly injects variables into template strings', () => {
    const raw = 'Hello {{ name }}, welcome to {{project_name}} (v{{version}})!';
    const vars = { name: 'Alice', project_name: 'SuperDocs', version: '2.0' };
    const injected = injectVariables(raw, vars);
    expect(injected).toBe('Hello Alice, welcome to SuperDocs (v2.0)!');
  });

  it('preserves unresolved placeholders when variables are missing', () => {
    const raw = 'Config: {{key}} = {{ value }}';
    const injected = injectVariables(raw, { key: 'PORT' });
    expect(injected).toBe('Config: PORT = {{ value }}');
  });

  it('renders templates and prompts list in gallery', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(
        <TemplateGallery
          templates={mockTemplates}
          prompts={mockPrompts}
          onLoadTemplates={vi.fn()}
          onLoadPrompts={vi.fn()}
          onApplyTemplate={vi.fn()}
          onApplyPrompt={vi.fn()}
        />
      );
    });

    expect(container.textContent).toContain('Professional README');
    expect(container.textContent).toContain('Standard enterprise README template');
    expect(container.textContent).toContain('API Reference Focus');

    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('selects template and applies with variable injection', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    const onApplyTemplate = vi.fn();

    act(() => {
      root.render(
        <TemplateGallery
          templates={mockTemplates}
          prompts={mockPrompts}
          onLoadTemplates={vi.fn()}
          onLoadPrompts={vi.fn()}
          onApplyTemplate={onApplyTemplate}
          onApplyPrompt={vi.fn()}
        />
      );
    });

    // Click template card
    const card = Array.from(container.querySelectorAll('button')).find(
      b => b.textContent?.includes('Professional README')
    );
    expect(card).toBeDefined();

    act(() => {
      card?.click();
    });

    expect(container.textContent).toContain('Fill in the template variables');

    // Click Apply Template
    const applyBtn = Array.from(container.querySelectorAll('button')).find(
      b => b.textContent?.includes('Apply Template')
    );
    expect(applyBtn).toBeDefined();

    act(() => {
      applyBtn?.click();
    });

    expect(onApplyTemplate).toHaveBeenCalledWith(
      mockTemplates[0],
      expect.objectContaining({ project_name: 'My App', author: 'Dev Team' })
    );

    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('selects prompt and applies with variable injection', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    const onApplyPrompt = vi.fn();

    act(() => {
      root.render(
        <TemplateGallery
          templates={mockTemplates}
          prompts={mockPrompts}
          onLoadTemplates={vi.fn()}
          onLoadPrompts={vi.fn()}
          onApplyTemplate={vi.fn()}
          onApplyPrompt={onApplyPrompt}
        />
      );
    });

    // Click prompt card
    const card = Array.from(container.querySelectorAll('button')).find(
      b => b.textContent?.includes('API Reference Focus')
    );
    expect(card).toBeDefined();

    act(() => {
      card?.click();
    });

    expect(container.textContent).toContain('Fill in the prompt variables');

    // Click Apply Prompt
    const applyBtn = Array.from(container.querySelectorAll('button')).find(
      b => b.textContent?.includes('Apply Prompt')
    );
    expect(applyBtn).toBeDefined();

    act(() => {
      applyBtn?.click();
    });

    expect(onApplyPrompt).toHaveBeenCalledWith(
      mockPrompts[0],
      expect.objectContaining({ module: 'auth' })
    );

    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('renders loading indicators when templatesLoading is true', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
      root.render(
        <TemplateGallery
          templates={undefined}
          prompts={undefined}
          templatesLoading={true}
          onLoadTemplates={vi.fn()}
          onLoadPrompts={vi.fn()}
          onApplyTemplate={vi.fn()}
          onApplyPrompt={vi.fn()}
        />
      );
    });

    expect(container.querySelectorAll('.animate-spin').length).toBeGreaterThan(0);

    act(() => {
      root.unmount();
    });
    container.remove();
  });
});
