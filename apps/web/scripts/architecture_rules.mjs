import { dirname, relative, resolve } from 'node:path';

export const capabilityBoundaries = {
  meta: {
    type: 'problem',
    schema: [],
    messages: {
      boundary:
        'Dependency {{target}} crosses an ownership boundary; use a feature public contract or app composition.',
    },
  },
  create(context) {
    const root = resolve(import.meta.dirname, '../src');
    const file = context.filename;
    const owner = relative(root, file).split('/');
    function check(node) {
      const name = node.source?.value;
      if (typeof name !== 'string') return;
      const targetPath = name.startsWith('@/')
        ? name.slice(2)
        : name.startsWith('.')
          ? relative(root, resolve(dirname(file), name))
          : undefined;
      if (!targetPath) return;
      const target = targetPath.split('/');
      const invalidShared =
        owner[0] === 'shared' && ['features', 'app'].includes(target[0]);
      const invalidFeature =
        owner[0] === 'features' &&
        (target[0] === 'app' ||
          (target[0] === 'features' &&
            target[1] !== owner[1] &&
            target.slice(2).join('/') !== 'public'));
      if (invalidShared || invalidFeature)
        context.report({ node, messageId: 'boundary', data: { target: name } });
    }
    return {
      ImportDeclaration: check,
      ExportNamedDeclaration: check,
      ExportAllDeclaration: check,
    };
  },
};
