import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

const root = resolve('src');
function files(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? files(path) : /\.tsx?$/.test(path) ? [path] : [];
  });
}
function imports(file: string): string[] {
  const tree = ts.createSourceFile(
    file,
    readFileSync(file, 'utf8'),
    ts.ScriptTarget.Latest,
    true,
  );
  const result: string[] = [];
  function visit(node: ts.Node) {
    if (
      (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
      node.moduleSpecifier &&
      ts.isStringLiteral(node.moduleSpecifier)
    )
      result.push(node.moduleSpecifier.text);
    ts.forEachChild(node, visit);
  }
  visit(tree);
  return result;
}
function dependencyPath(file: string, name: string): string | undefined {
  if (name.startsWith('@/')) return name.slice(2);
  if (name.startsWith('.'))
    return relative(root, resolve(dirname(file), name)).replaceAll('\\', '/');
}

describe('frontend architecture', () => {
  it('features expose cross-feature dependencies only through public contracts', () => {
    const violations: string[] = [];
    for (const file of files(root)) {
      const owner = relative(root, file).split('/');
      for (const name of imports(file)) {
        const target = dependencyPath(file, name)?.split('/');
        if (!target) continue;
        if (owner[0] === 'shared' && ['features', 'app'].includes(target[0]))
          violations.push(`${file}: ${name}`);
        if (owner[0] !== 'features') continue;
        if (target[0] === 'app') violations.push(`${file}: ${name}`);
        if (
          target[0] === 'features' &&
          target[1] !== owner[1] &&
          target.slice(2).join('/') !== 'public'
        )
          violations.push(`${file}: ${name}`);
      }
    }
    expect(violations).toEqual([]);
  });

  it('feature dependencies have no cycles, including type-only imports', () => {
    const graph = new Map<string, Set<string>>();
    for (const file of files(join(root, 'features'))) {
      const owner = relative(root, file).split('/')[1];
      const edges = graph.get(owner) ?? new Set<string>();
      graph.set(owner, edges);
      for (const name of imports(file)) {
        const target = dependencyPath(file, name)?.split('/');
        if (target?.[0] === 'features' && target[1] !== owner) edges.add(target[1]);
      }
    }
    function visit(feature: string, path: string[]) {
      expect(path, `Feature cycle: ${[...path, feature].join(' -> ')}`).not.toContain(
        feature,
      );
      for (const next of graph.get(feature) ?? []) visit(next, [...path, feature]);
    }
    for (const feature of graph.keys()) visit(feature, []);
  });
});
