import { useState, useEffect, useCallback, useMemo } from 'react';
import { Template, Prompt, TemplateVariable, PromptVariable } from '../types/superdocs';

interface TemplateGalleryProps {
  templates?: Template[];
  prompts?: Prompt[];
  templatesLoading?: boolean;
  onLoadTemplates: () => void;
  onLoadPrompts: () => void;
  onApplyTemplate: (template: Template, variables: Record<string, string>) => void;
  onApplyPrompt: (prompt: Prompt, variables: Record<string, string>) => void;
  disabled?: boolean;
}

export function injectVariables(template: string, variables: Record<string, string>): string {
  return template.replace(/\{\{\s*([\w.-]+)\s*\}\}/g, (match, key: string) => {
    return variables[key] !== undefined ? variables[key] : match;
  });
}

type SelectedKind = 'template' | 'prompt';

interface SelectedItem {
  kind: SelectedKind;
  id: string;
}

export function TemplateGallery({
  templates,
  prompts,
  templatesLoading,
  onLoadTemplates,
  onLoadPrompts,
  onApplyTemplate,
  onApplyPrompt,
  disabled,
}: TemplateGalleryProps) {
  const [selected, setSelected] = useState<SelectedItem | null>(null);
  const [variableValues, setVariableValues] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!templates && !templatesLoading) onLoadTemplates();
    if (!prompts && !templatesLoading) onLoadPrompts();
  }, [templates, prompts, templatesLoading, onLoadTemplates, onLoadPrompts]);

  const activeTemplate = useMemo(
    () => (selected?.kind === 'template' ? templates?.find(t => t.id === selected.id) : undefined),
    [selected, templates]
  );
  const activePrompt = useMemo(
    () => (selected?.kind === 'prompt' ? prompts?.find(p => p.id === selected.id) : undefined),
    [selected, prompts]
  );

  const selectTemplate = useCallback((template: Template) => {
    setSelected({ kind: 'template', id: template.id });
    const initial: Record<string, string> = {};
    template.variables.forEach((v: TemplateVariable) => {
      initial[v.name] = v.default_value ?? '';
    });
    setVariableValues(initial);
  }, []);

  const selectPrompt = useCallback((prompt: Prompt) => {
    setSelected({ kind: 'prompt', id: prompt.id });
    const initial: Record<string, string> = {};
    prompt.variables.forEach((v: PromptVariable) => {
      initial[v.name] = v.default_value ?? '';
    });
    setVariableValues(initial);
  }, []);

  const handleApply = useCallback(() => {
    if (activeTemplate) {
      onApplyTemplate(activeTemplate, variableValues);
    } else if (activePrompt) {
      onApplyPrompt(activePrompt, variableValues);
    }
  }, [activeTemplate, activePrompt, variableValues, onApplyTemplate, onApplyPrompt]);

  const activeVariables = activeTemplate?.variables ?? activePrompt?.variables ?? [];

  return (
    <div className="space-y-6">
      {/* Templates section */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold text-gray-900">Template Gallery</h2>
            <span className="text-[10px] bg-primary-100 text-primary-700 px-2 py-0.5 rounded-full font-semibold">
              PRE-BUILT
            </span>
          </div>
          <button
            onClick={onLoadTemplates}
            disabled={templatesLoading}
            className="px-3 py-1.5 text-xs font-semibold bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50 transition-colors focus:ring-2 focus:ring-gray-500 focus:ring-offset-2 shadow-xs"
          >
            {templatesLoading ? 'Loading...' : 'Refresh'}
          </button>
        </div>

        {templatesLoading && (!templates || templates.length === 0) ? (
          <div className="flex items-center gap-2 text-sm text-gray-600 py-8 justify-center">
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary-600" />
            <span>Loading templates...</span>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {(templates || []).map((template) => (
              <button
                key={template.id}
                onClick={() => selectTemplate(template)}
                disabled={disabled}
                className={`text-left border rounded-xl p-4 transition-all card-hover disabled:opacity-50 cursor-pointer ${
                  selected?.kind === 'template' && selected.id === template.id
                    ? 'border-primary-500 bg-primary-50 ring-2 ring-primary-500 shadow-sm'
                    : 'border-gray-200 bg-white hover:border-gray-300 shadow-xs'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="font-semibold text-gray-900 text-sm">{template.name}</p>
                  <span className="px-2 py-0.5 text-[10px] font-semibold bg-gray-100 text-gray-600 rounded uppercase tracking-wider border border-gray-200">
                    {template.document_type}
                  </span>
                </div>
                <p className="text-xs text-gray-500 mt-1.5 line-clamp-2">{template.description}</p>
              </button>
            ))}
            {templates && templates.length === 0 && (
              <p className="text-sm text-gray-500 col-span-full">No templates available.</p>
            )}
          </div>
        )}
      </section>

      {/* Prompts section */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-bold text-gray-900">Prompt Library</h2>
            <span className="text-[10px] bg-gray-100 text-gray-700 px-2 py-0.5 rounded-full font-semibold">
              RECIPES
            </span>
          </div>
          <button
            onClick={onLoadPrompts}
            disabled={templatesLoading}
            className="px-3 py-1.5 text-xs font-semibold bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50 transition-colors focus:ring-2 focus:ring-gray-500 focus:ring-offset-2 shadow-xs"
          >
            {templatesLoading ? 'Loading...' : 'Refresh'}
          </button>
        </div>

        {templatesLoading && (!prompts || prompts.length === 0) ? (
          <div className="flex items-center gap-2 text-sm text-gray-600 py-8 justify-center">
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary-600" />
            <span>Loading prompts...</span>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {(prompts || []).map((prompt) => (
              <button
                key={prompt.id}
                onClick={() => selectPrompt(prompt)}
                disabled={disabled}
                className={`text-left border rounded-xl p-4 transition-all card-hover disabled:opacity-50 cursor-pointer ${
                  selected?.kind === 'prompt' && selected.id === prompt.id
                    ? 'border-primary-500 bg-primary-50 ring-2 ring-primary-500 shadow-sm'
                    : 'border-gray-200 bg-white hover:border-gray-300 shadow-xs'
                }`}
              >
                <p className="font-semibold text-gray-900 text-sm">{prompt.name}</p>
                <p className="text-xs text-gray-500 mt-1.5 line-clamp-2">{prompt.description}</p>
              </button>
            ))}
            {prompts && prompts.length === 0 && (
              <p className="text-sm text-gray-500 col-span-full">No prompts available.</p>
            )}
          </div>
        )}
      </section>

      {/* Variable injection form */}
      {selected && (activeTemplate || activePrompt) && (
        <section className="border border-gray-200 rounded-xl p-5 bg-white shadow-sm animate-fade-in">
          <h3 className="text-sm font-bold text-gray-900 mb-1">
            {activeTemplate ? activeTemplate.name : activePrompt?.name}
          </h3>
          <p className="text-xs text-gray-500 mb-4">
            {activeTemplate ? 'Fill in the template variables below, then apply to start a document.' : 'Fill in the prompt variables below, then apply to instruct SuperDocs.'}
          </p>

          {activeVariables.length > 0 ? (
            <div className="space-y-3.5 mb-5">
              {activeVariables.map((variable) => (
                <div key={variable.name}>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    {variable.name}
                    {variable.required && <span className="text-red-500"> *</span>}
                  </label>
                  <input
                    type="text"
                    value={variableValues[variable.name] ?? ''}
                    onChange={(e) => setVariableValues(prev => ({ ...prev, [variable.name]: e.target.value }))}
                    placeholder={variable.description}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 text-xs font-mono"
                  />
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-gray-500 mb-4">This {activeTemplate ? 'template' : 'prompt'} has no variables.</p>
          )}

          <div className="bg-gray-50 border border-gray-200 rounded-xl p-3.5 mb-5">
            <p className="text-xs font-semibold text-gray-600 mb-1.5">Preview</p>
            <pre className="whitespace-pre-wrap text-xs font-mono text-gray-800 max-h-40 overflow-auto">
              {injectVariables(activeTemplate?.default_content ?? activePrompt?.template ?? '', variableValues)}
            </pre>
          </div>

          <button
            onClick={handleApply}
            disabled={disabled}
            className="w-full px-4 py-2.5 bg-primary-600 text-white rounded-xl font-semibold hover:bg-primary-700 disabled:opacity-50 transition-all focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 shadow-xs"
          >
            Apply {activeTemplate ? 'Template' : 'Prompt'}
          </button>
        </section>
      )}
    </div>
  );
}
