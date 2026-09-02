import { spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { format } from 'prettier';

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const apiRoot = resolve(webRoot, '..', 'api');
const outputPath = resolve(
  webRoot,
  'src',
  'shared',
  'api',
  'generated',
  'assistant.ts',
);
const check = process.argv.includes('--check');

const command = [
  'run',
  '--directory',
  apiRoot,
  '--frozen',
  'python',
  '-c',
  [
    'import json',
    'from disaster_monitor.presentation.http.api import create_schema_app',
    'print(json.dumps(create_schema_app().openapi(), sort_keys=True, separators=(",", ":")))',
  ].join('; '),
];
const result = spawnSync('uv', command, { encoding: 'utf8', cwd: webRoot });
if (result.status !== 0) {
  process.stderr.write(result.stderr || 'OpenAPI schema generation failed.\n');
  process.exit(result.status ?? 1);
}

const document = JSON.parse(result.stdout);
const schemas = document.components?.schemas;
if (!schemas || typeof schemas !== 'object') {
  throw new Error('The backend OpenAPI document has no component schemas.');
}

function literal(value) {
  return typeof value === 'string' ? JSON.stringify(value) : String(value);
}

function referenceName(reference) {
  return reference.split('/').at(-1);
}

function schemaType(schema) {
  if (!schema || typeof schema !== 'object') return 'unknown';
  if (schema.$ref) return referenceName(schema.$ref);
  if ('const' in schema) return literal(schema.const);
  if (schema.enum) return schema.enum.map(literal).join(' | ');
  if (schema.anyOf) return schema.anyOf.map(schemaType).join(' | ');
  if (schema.oneOf) return schema.oneOf.map(schemaType).join(' | ');
  if (schema.allOf) return schema.allOf.map(schemaType).join(' & ');
  if (schema.prefixItems) {
    return `[${schema.prefixItems.map(schemaType).join(', ')}]`;
  }
  if (schema.type === 'array') return `Array<${schemaType(schema.items)}>`;
  if (schema.type === 'object' || schema.properties || schema.additionalProperties) {
    const required = new Set(schema.required ?? []);
    const fields = Object.entries(schema.properties ?? {}).map(
      ([name, value]) =>
        `  ${JSON.stringify(name)}${required.has(name) ? '' : '?'}: ${schemaType(value)};`,
    );
    if (schema.additionalProperties) {
      fields.push(`  [key: string]: ${schemaType(schema.additionalProperties)};`);
    }
    return fields.length ? `{\n${fields.join('\n')}\n}` : 'Record<string, unknown>';
  }
  if (schema.type === 'string') return 'string';
  if (schema.type === 'integer' || schema.type === 'number') return 'number';
  if (schema.type === 'boolean') return 'boolean';
  if (schema.type === 'null') return 'null';
  return 'unknown';
}

const validationKeywords = new Set([
  '$ref',
  'additionalProperties',
  'allOf',
  'anyOf',
  'const',
  'enum',
  'exclusiveMaximum',
  'exclusiveMinimum',
  'format',
  'items',
  'maxItems',
  'maxLength',
  'maximum',
  'minItems',
  'minLength',
  'minimum',
  'oneOf',
  'pattern',
  'prefixItems',
  'properties',
  'required',
  'type',
]);
const annotationKeywords = new Set([
  'default',
  'deprecated',
  'discriminator',
  'description',
  'example',
  'examples',
  'readOnly',
  'title',
  'writeOnly',
]);

function runtimeSchema(schema) {
  if (Array.isArray(schema)) return schema.map(runtimeSchema);
  if (!schema || typeof schema !== 'object') return schema;
  const unsupported = Object.keys(schema).filter(
    (name) => !validationKeywords.has(name) && !annotationKeywords.has(name),
  );
  if (unsupported.length) {
    throw new Error(
      `Runtime validator does not support OpenAPI keywords: ${unsupported.join(', ')}`,
    );
  }
  return Object.fromEntries(
    Object.entries(schema)
      .filter(([name]) => validationKeywords.has(name))
      .map(([name, value]) => [
        name,
        name === 'properties'
          ? Object.fromEntries(
              Object.entries(value).map(([field, fieldSchema]) => [
                field,
                runtimeSchema(fieldSchema),
              ]),
            )
          : runtimeSchema(value),
      ]),
  );
}

function referencedSchemas(schema) {
  const names = new Set();
  const pending = [schema];
  while (pending.length) {
    const value = pending.pop();
    if (Array.isArray(value)) {
      pending.push(...value);
    } else if (value && typeof value === 'object') {
      if (typeof value.$ref === 'string') names.add(referenceName(value.$ref));
      pending.push(...Object.values(value));
    }
  }
  return names;
}

const runtimeSchemaNames = new Set([
  'AssistantResponse',
  'ConversationResponse',
  'ConversationSummaryResponse',
  'SourceCatalogResponse',
  'WeatherAlertsSnapshotResponse',
]);
const pendingRuntimeSchemas = [...runtimeSchemaNames];
while (pendingRuntimeSchemas.length) {
  const name = pendingRuntimeSchemas.pop();
  const schema = schemas[name];
  if (!schema) throw new Error(`The backend OpenAPI schema is missing ${name}.`);
  for (const referenced of referencedSchemas(schema)) {
    if (!runtimeSchemaNames.has(referenced)) {
      runtimeSchemaNames.add(referenced);
      pendingRuntimeSchemas.push(referenced);
    }
  }
}
const runtimeSchemas = Object.fromEntries(
  [...runtimeSchemaNames]
    .sort((left, right) => left.localeCompare(right))
    .map((name) => [name, runtimeSchema(schemas[name])]),
);

const body = Object.keys(schemas)
  .sort((left, right) => left.localeCompare(right))
  .map((name) => `export type ${name} = ${schemaType(schemas[name])};`)
  .join('\n\n');
const unformattedOutput = [
  '// Generated from the DisasterMonitor backend OpenAPI schema.',
  '// Run `npm run generate:api-contract` after backend schema changes.',
  '',
  "import { matchesOpenApiSchema } from '@/shared/api/openapiSchema';",
  '',
  `const apiSchemas = ${JSON.stringify(runtimeSchemas, null, 2)} as const;`,
  '',
  'export type ApiSchemaName = keyof typeof apiSchemas;',
  '',
  'export function matchesApiSchema(name: ApiSchemaName, value: unknown): boolean {',
  '  return matchesOpenApiSchema(value, apiSchemas[name], apiSchemas);',
  '}',
  '',
  body,
  '',
].join('\n');
const output = await format(unformattedOutput, {
  parser: 'typescript',
  printWidth: 88,
  semi: true,
  singleQuote: true,
  trailingComma: 'all',
});

if (check) {
  let existing = '';
  try {
    existing = readFileSync(outputPath, 'utf8');
  } catch {
    // The comparison below reports the actionable stale-file message.
  }
  if (existing !== output) {
    process.stderr.write(
      'Generated assistant API contract is stale. Run npm run generate:api-contract.\n',
    );
    process.exit(1);
  }
} else {
  writeFileSync(outputPath, output, 'utf8');
}
