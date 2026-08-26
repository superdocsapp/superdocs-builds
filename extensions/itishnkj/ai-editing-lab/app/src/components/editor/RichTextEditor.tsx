import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Extension } from '@tiptap/react';
import { Table, TableHeader, TableKit } from '@tiptap/extension-table';

const ChunkedTable = Table.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      'data-chunk-id': {
        default: null,
        parseHTML: element => element.getAttribute('data-chunk-id'),
        renderHTML: attributes =>
          attributes['data-chunk-id']
            ? { 'data-chunk-id': attributes['data-chunk-id'] }
            : {},
      },
    };
  },
});

const ScopedTableHeader = TableHeader.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      scope: {
        default: null,
        parseHTML: element => {
          const value = element.getAttribute('scope');
          return /^(?:col|row|colgroup|rowgroup)$/i.test(value ?? '')
            ? value?.toLowerCase()
            : null;
        },
        renderHTML: attributes =>
          attributes.scope ? { scope: attributes.scope } : {},
      },
    };
  },
});

const ChunkIdExtension = Extension.create({
  name: 'chunkId',
  addGlobalAttributes() {
    return [
      {
        types: [
          'heading',
          'paragraph',
          'bulletList',
          'orderedList',
          'listItem',
          'blockquote',
          'link',
          'bold',
          'italic',
          'underline',
          'hardBreak',
          'tableRow',
          'tableCell',
          'tableHeader',
        ],
        attributes: {
          'data-chunk-id': {
            default: null,
            parseHTML: element => element.getAttribute('data-chunk-id'),
            renderHTML: attributes => {
              if (!attributes['data-chunk-id']) {
                return {}
              }
              return {
                'data-chunk-id': attributes['data-chunk-id'],
              }
            },
          },
        },
      },
    ]
  },
})

import { forwardRef, useEffect, useImperativeHandle, useState } from 'react';
import { cn } from '@/lib/utils';
import { 
  Bold, Italic, Underline as UnderlineIcon, 
  List, ListOrdered, Quote, Heading1, Heading2, Heading3,
  Undo, Redo, Link as LinkIcon, Table2, Rows3, Columns3, Trash2,
} from 'lucide-react';
import { Toggle } from '@/components/ui/toggle';
import { Separator } from '@/components/ui/separator';
import { Button } from '@/components/ui/button';

interface RichTextEditorProps {
  content: string;
  onChange: (html: string) => void;
  onSelectionChange?: (text: string, html: string, from: number, to: number) => void;
  className?: string;
  readOnly?: boolean;
}

export type RichTextEditorHandle = {
  replaceRange: (from: number, to: number, html: string) => string | null;
};

export const RichTextEditor = forwardRef<
  RichTextEditorHandle,
  RichTextEditorProps
>(function RichTextEditor(
  { content, onChange, onSelectionChange, className, readOnly = false },
  ref,
) {
  const [isMounted, setIsMounted] = useState(false);
  
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        link: {
          openOnClick: false,
        },
      }),
      TableKit.configure({
        table: false,
        tableHeader: false,
      }),
      ChunkedTable.configure({
        HTMLAttributes: { class: 'editor-table' },
      }),
      ScopedTableHeader,
      ChunkIdExtension,
    ],
    content,
    editable: !readOnly,
    onUpdate: ({ editor }) => {
      onChange(editor.getHTML());
    },
    onSelectionUpdate: ({ editor }) => {
      if (onSelectionChange) {
        const { from, to } = editor.state.selection;
        const text = editor.state.doc.textBetween(from, to, ' ');
        const escaped = text
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;');
        onSelectionChange(text, escaped, from, to);
      }
    }
  });

  useImperativeHandle(
    ref,
    () => ({
      replaceRange(from, to, html) {
        if (!editor) return null;
        const applied = editor
          .chain()
          .focus()
          .insertContentAt({ from, to }, html)
          .run();
        return applied ? editor.getHTML() : null;
      },
    }),
    [editor],
  );

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (editor && content !== editor.getHTML()) {
      editor.commands.setContent(content, { emitUpdate: false });
    }
  }, [content, editor]);

  if (!editor || !isMounted) return null;

  return (
    <div className={cn("flex flex-col border rounded-md bg-card overflow-hidden h-full shadow-sm", className)}>
      {!readOnly && (
        <div className="flex flex-wrap items-center gap-1 border-b bg-muted/40 p-1">
          <Toggle
            size="sm"
            pressed={editor.isActive('heading', { level: 1 })}
            onPressedChange={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
            aria-label="Toggle Heading 1"
          >
            <Heading1 className="h-4 w-4" />
          </Toggle>
          <Toggle
            size="sm"
            pressed={editor.isActive('heading', { level: 2 })}
            onPressedChange={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
            aria-label="Toggle Heading 2"
          >
            <Heading2 className="h-4 w-4" />
          </Toggle>
          <Toggle
            size="sm"
            pressed={editor.isActive('heading', { level: 3 })}
            onPressedChange={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
            aria-label="Toggle Heading 3"
          >
            <Heading3 className="h-4 w-4" />
          </Toggle>
          
          <Separator orientation="vertical" className="h-6 mx-1" />
          
          <Toggle
            size="sm"
            pressed={editor.isActive('bold')}
            onPressedChange={() => editor.chain().focus().toggleBold().run()}
            aria-label="Toggle Bold"
          >
            <Bold className="h-4 w-4" />
          </Toggle>
          <Toggle
            size="sm"
            pressed={editor.isActive('italic')}
            onPressedChange={() => editor.chain().focus().toggleItalic().run()}
            aria-label="Toggle Italic"
          >
            <Italic className="h-4 w-4" />
          </Toggle>
          <Toggle
            size="sm"
            pressed={editor.isActive('underline')}
            onPressedChange={() => editor.chain().focus().toggleUnderline().run()}
            aria-label="Toggle Underline"
          >
            <UnderlineIcon className="h-4 w-4" />
          </Toggle>
          
          <Separator orientation="vertical" className="h-6 mx-1" />
          
          <Toggle
            size="sm"
            pressed={editor.isActive('bulletList')}
            onPressedChange={() => editor.chain().focus().toggleBulletList().run()}
            aria-label="Toggle Bullet List"
          >
            <List className="h-4 w-4" />
          </Toggle>
          <Toggle
            size="sm"
            pressed={editor.isActive('orderedList')}
            onPressedChange={() => editor.chain().focus().toggleOrderedList().run()}
            aria-label="Toggle Ordered List"
          >
            <ListOrdered className="h-4 w-4" />
          </Toggle>
          <Toggle
            size="sm"
            pressed={editor.isActive('blockquote')}
            onPressedChange={() => editor.chain().focus().toggleBlockquote().run()}
            aria-label="Toggle Blockquote"
          >
            <Quote className="h-4 w-4" />
          </Toggle>

          <Separator orientation="vertical" className="h-6 mx-1" />

          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              const previousUrl = editor.getAttributes('link').href;
              const url = window.prompt('URL', previousUrl);
              if (url === null) return;
              if (url === '') {
                editor.chain().focus().extendMarkRange('link').unsetLink().run();
                return;
              }
              editor.chain().focus().extendMarkRange('link').setLink({ href: url }).run();
            }}
            className={cn(editor.isActive('link') && "bg-accent text-accent-foreground")}
            aria-label="Toggle Link"
          >
            <LinkIcon className="h-4 w-4" />
          </Button>
          
          <Separator orientation="vertical" className="h-6 mx-1" />

          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              editor
                .chain()
                .focus()
                .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
                .run()
            }
            aria-label="Insert 3 by 3 table"
            title="Insert table"
          >
            <Table2 className="h-4 w-4" />
          </Button>
          {editor.isActive('table') && (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => editor.chain().focus().addRowAfter().run()}
                aria-label="Add table row"
                title="Add row"
              >
                <Rows3 className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => editor.chain().focus().addColumnAfter().run()}
                aria-label="Add table column"
                title="Add column"
              >
                <Columns3 className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => editor.chain().focus().deleteTable().run()}
                aria-label="Delete table"
                title="Delete table"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </>
          )}

          <div className="flex-1" />

          <Button
            variant="ghost"
            size="sm"
            onClick={() => editor.chain().focus().undo().run()}
            disabled={!editor.can().undo()}
          >
            <Undo className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => editor.chain().focus().redo().run()}
            disabled={!editor.can().redo()}
          >
            <Redo className="h-4 w-4" />
          </Button>
        </div>
      )}
      
      <div className="flex-1 overflow-y-auto p-4 cursor-text" onClick={() => editor.commands.focus()}>
        <EditorContent editor={editor} className="prose prose-sm dark:prose-invert max-w-none w-full h-full min-h-[200px]" />
      </div>
    </div>
  );
});
