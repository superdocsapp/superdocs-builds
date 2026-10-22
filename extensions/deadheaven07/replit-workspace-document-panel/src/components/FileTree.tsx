/// <reference lib="dom" />
// @jsxImportSource react
import { useState, useCallback, useMemo } from 'react';
import * as React from 'react';
import { FileTreeNode } from '../services/replit';

interface FileTreeProps {
  nodes: FileTreeNode[];
  onSelectionChange: (selectedPaths: string[]) => void;
  selectedPaths: string[];
  searchQuery: string;
  onSearchChange: (query: string) => void;
}

const FILE_ICONS: Record<string, string> = {
  ts: '🟦',
  tsx: '⚛️',
  js: '🟨',
  jsx: '⚛️',
  py: '🐍',
  rs: '🦀',
  go: '🔵',
  java: '☕',
  json: '📋',
  yaml: '📋',
  yml: '📋',
  toml: '📋',
  md: '📄',
  txt: '📄',
  css: '🎨',
  scss: '🎨',
  html: '🌐',
  sh: '💻',
  dockerfile: '🐳',
  dockerignore: '🐳',
  gitignore: '🙈',
  env: '🔐',
};

function getFileIcon(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase();
  return ext && FILE_ICONS[ext] ? FILE_ICONS[ext] : '📄';
}

function FileTreeNodeComponent({
  node,
  selectedPaths,
  onToggle,
  level = 0,
  searchQuery = '',
}: {
  node: FileTreeNode;
  selectedPaths: string[];
  onToggle: (path: string) => void;
  level: number;
  searchQuery: string;
}) {
  const [expanded, setExpanded] = useState(!node.ignored);
  const isSelected = selectedPaths.includes(node.path);
  const hasChildren = node.children && node.children.length > 0;
  const matchesSearch = searchQuery ? node.name.toLowerCase().includes(searchQuery.toLowerCase()) : true;

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (node.isDirectory) {
      setExpanded(!expanded);
    } else if (!node.ignored) {
      onToggle(node.path);
    }
  };

  const handleCheckboxChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.stopPropagation();
    onToggle(node.path);
  };

  const highlightText = (text: string, query: string) => {
    if (!query) return <span>{text}</span>;
    const parts = text.toLowerCase().split(query.toLowerCase());
    return (
      <span>
        {parts.map((part, i) => (
          <React.Fragment key={i}>
            {i > 0 && <mark className="search-highlight">{query}</mark>}
            {part}
          </React.Fragment>
        ))}
      </span>
    );
  };

  if (node.ignored) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-gray-400 opacity-50 py-1" style={{ paddingLeft: `${level * 16 + 10}px` }}>
        <span className="w-4 h-4" />
        <span className="line-through">{node.name}</span>
        {node.ignoreReason && <span className="italic"> ({node.ignoreReason})</span>}
      </div>
    );
  }

  if (searchQuery && !matchesSearch && !hasChildren) {
    return null;
  }

  return (
    <div>
      <div
        className={`flex items-center gap-1.5 py-1 px-2 cursor-pointer rounded-lg transition-all ${
          isSelected ? 'bg-primary-50 text-primary-700 font-semibold' : 'hover:bg-gray-100 text-gray-700'
        }`}
        style={{ paddingLeft: `${level * 16 + 10}px` }}
        onClick={handleClick}
      >
        {hasChildren && (
          <button
            className="p-0.5 text-gray-400 hover:text-gray-700 rounded transition-colors"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
            aria-label={expanded ? 'Collapse' : 'Expand'}
            aria-expanded={expanded}
          >
            {expanded ? '▾' : '▸'}
          </button>
        )}
        {!hasChildren && <span className="w-4" />}
        
        <input
          type="checkbox"
          checked={isSelected}
          onChange={handleCheckboxChange}
          className="w-4 h-4 text-primary-600 rounded border-gray-300 focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
          disabled={node.isDirectory}
          aria-label={node.isDirectory ? undefined : `Select ${node.name}`}
        />
        
        <span className={`truncate-text flex-1 min-w-0 text-xs ${isSelected ? 'font-semibold text-primary-700' : 'text-gray-800'}`}>
          <span aria-hidden="true">{getFileIcon(node.name)} </span>
          {highlightText(node.name, searchQuery)}
        </span>
        
        {node.isDirectory && hasChildren && (
          <span className="text-[10px] text-gray-400 ml-auto whitespace-nowrap px-1.5 py-0.2 bg-gray-100 rounded-md">
            {node.children!.length} item{node.children!.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {expanded && hasChildren && (
        <div role="group" aria-label={`${node.name} contents`}>
          {node.children!.map((child) => (
            <FileTreeNodeComponent
              key={child.path}
              node={child}
              selectedPaths={selectedPaths}
              onToggle={onToggle}
              level={level + 1}
              searchQuery={searchQuery}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function FileTree({ nodes, onSelectionChange, selectedPaths, searchQuery = '', onSearchChange }: FileTreeProps) {
  const handleToggle = useCallback((path: string) => {
    const newPaths = selectedPaths.includes(path)
      ? selectedPaths.filter((p) => p !== path)
      : [...selectedPaths, path];
    onSelectionChange(newPaths);
  }, [selectedPaths, onSelectionChange]);

  const allSelectablePaths = useMemo(() => {
    const paths: string[] = [];
    const traverse = (nodes: FileTreeNode[]) => {
      for (const node of nodes) {
        if (!node.isDirectory && !node.ignored) {
          paths.push(node.path);
        }
        if (node.children) {
          traverse(node.children);
        }
      }
    };
    traverse(nodes);
    return paths;
  }, [nodes]);

  const isAllSelected = allSelectablePaths.length > 0 && allSelectablePaths.every(p => selectedPaths.includes(p));

  const handleSelectAll = useCallback(() => {
    if (isAllSelected) {
      onSelectionChange([]);
    } else {
      onSelectionChange(allSelectablePaths);
    }
  }, [isAllSelected, allSelectablePaths, onSelectionChange]);

  const filteredNodes = useMemo(() => {
    if (!searchQuery) return nodes;
    
    const filterNodes = (nodes: FileTreeNode[]): FileTreeNode[] => {
      return nodes.filter(node => {
        const matches = node.name.toLowerCase().includes(searchQuery.toLowerCase());
        if (node.isDirectory && node.children) {
          const filteredChildren = filterNodes(node.children);
          return matches || filteredChildren.length > 0;
        }
        return matches;
      });
    };
    
    return filterNodes(nodes);
  }, [nodes, searchQuery]);

  return (
    <div className="border border-gray-200 rounded-xl bg-white overflow-hidden shadow-xs flex flex-col">
      {/* Toolbar */}
      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-bold text-gray-900">Project Files</h3>
          <span className="px-2 py-0.5 text-xs font-semibold bg-primary-100 text-primary-700 rounded-full">
            {selectedPaths.length} selected
          </span>
        </div>
        
        <div className="flex items-center gap-2 ml-auto">
          <button
            onClick={handleSelectAll}
            disabled={allSelectablePaths.length === 0}
            className="px-2.5 py-1 text-xs font-semibold text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-xs"
            aria-label={isAllSelected ? 'Deselect all' : 'Select all'}
          >
            {isAllSelected ? 'Clear' : 'Select All'}
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="px-4 py-2.5 border-b border-gray-200 bg-white">
        <label htmlFor="file-search" className="sr-only">Search files</label>
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            id="file-search"
            type="text"
            placeholder="Search files..."
            value={searchQuery}
            onChange={(e) => {
              onSearchChange(e.target.value);
            }}
            className="w-full pl-9 pr-3 py-1.5 text-xs border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 bg-white"
            aria-label="Search files"
          />
        </div>
      </div>

      {/* File Tree List */}
      <div className="max-h-[calc(100%-140px)] overflow-auto p-2" role="tree" aria-label="Project files">
        {filteredNodes.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-gray-500">
            <p className="text-xs">No files found</p>
          </div>
        ) : (
          <div role="tree" aria-label="Project files">
            {filteredNodes.map((node) => (
              <FileTreeNodeComponent
                key={node.path}
                node={node}
                selectedPaths={selectedPaths}
                onToggle={handleToggle}
                level={0}
                searchQuery={searchQuery}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}