type JsonObject = Record<string, unknown>;
type SchemaCatalog = Record<string, unknown>;

export function matchesOpenApiSchema(
  value: unknown,
  schema: unknown,
  catalog: SchemaCatalog,
): boolean {
  if (!isObject(schema)) return true;

  const reference = schema.$ref;
  if (typeof reference === 'string') {
    const name = reference.split('/').at(-1);
    return (
      name !== undefined &&
      Object.hasOwn(catalog, name) &&
      matchesOpenApiSchema(value, catalog[name], catalog)
    );
  }
  if (
    Array.isArray(schema.anyOf) &&
    !schema.anyOf.some((candidate) => matchesOpenApiSchema(value, candidate, catalog))
  ) {
    return false;
  }
  if (
    Array.isArray(schema.oneOf) &&
    schema.oneOf.filter((candidate) => matchesOpenApiSchema(value, candidate, catalog))
      .length !== 1
  ) {
    return false;
  }
  if (
    Array.isArray(schema.allOf) &&
    !schema.allOf.every((candidate) => matchesOpenApiSchema(value, candidate, catalog))
  ) {
    return false;
  }
  if ('const' in schema && !Object.is(value, schema.const)) return false;
  if (
    Array.isArray(schema.enum) &&
    !schema.enum.some((item) => Object.is(item, value))
  ) {
    return false;
  }

  switch (schema.type) {
    case 'null':
      return value === null;
    case 'boolean':
      return typeof value === 'boolean';
    case 'integer':
      return Number.isInteger(value) && numberConstraints(value as number, schema);
    case 'number':
      return (
        typeof value === 'number' &&
        Number.isFinite(value) &&
        numberConstraints(value, schema)
      );
    case 'string':
      return typeof value === 'string' && stringConstraints(value, schema);
    case 'array':
      return Array.isArray(value) && arrayConstraints(value, schema, catalog);
    case 'object':
      return isObject(value) && objectConstraints(value, schema, catalog);
    default:
      return true;
  }
}

function numberConstraints(value: number, schema: JsonObject): boolean {
  return (
    Number.isFinite(value) &&
    (typeof schema.minimum !== 'number' || value >= schema.minimum) &&
    (typeof schema.maximum !== 'number' || value <= schema.maximum) &&
    (typeof schema.exclusiveMinimum !== 'number' || value > schema.exclusiveMinimum) &&
    (typeof schema.exclusiveMaximum !== 'number' || value < schema.exclusiveMaximum)
  );
}

function stringConstraints(value: string, schema: JsonObject): boolean {
  if (typeof schema.minLength === 'number' && value.length < schema.minLength) {
    return false;
  }
  if (typeof schema.maxLength === 'number' && value.length > schema.maxLength) {
    return false;
  }
  if (typeof schema.pattern === 'string' && !new RegExp(schema.pattern).test(value)) {
    return false;
  }
  if (schema.format === 'date-time') {
    const rfc3339 =
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
    if (!rfc3339.test(value) || Number.isNaN(Date.parse(value))) return false;
  }
  return true;
}

function arrayConstraints(
  value: unknown[],
  schema: JsonObject,
  catalog: SchemaCatalog,
): boolean {
  if (typeof schema.minItems === 'number' && value.length < schema.minItems) {
    return false;
  }
  if (typeof schema.maxItems === 'number' && value.length > schema.maxItems) {
    return false;
  }
  if (
    Array.isArray(schema.prefixItems) &&
    schema.prefixItems.some(
      (item, index) =>
        index >= value.length || !matchesOpenApiSchema(value[index], item, catalog),
    )
  ) {
    return false;
  }
  if (schema.items === false) {
    return (
      !Array.isArray(schema.prefixItems) || value.length <= schema.prefixItems.length
    );
  }
  return (
    schema.items === undefined ||
    value.every((item) => matchesOpenApiSchema(item, schema.items, catalog))
  );
}

function objectConstraints(
  value: JsonObject,
  schema: JsonObject,
  catalog: SchemaCatalog,
): boolean {
  const required = Array.isArray(schema.required) ? schema.required : [];
  if (
    required.some((name) => typeof name !== 'string' || !Object.hasOwn(value, name))
  ) {
    return false;
  }
  const properties = isObject(schema.properties) ? schema.properties : {};
  for (const [name, propertySchema] of Object.entries(properties)) {
    if (
      Object.hasOwn(value, name) &&
      !matchesOpenApiSchema(value[name], propertySchema, catalog)
    ) {
      return false;
    }
  }
  const unknownNames = Object.keys(value).filter(
    (name) => !Object.hasOwn(properties, name),
  );
  if (schema.additionalProperties === false && unknownNames.length > 0) return false;
  if (isObject(schema.additionalProperties)) {
    return unknownNames.every((name) =>
      matchesOpenApiSchema(value[name], schema.additionalProperties, catalog),
    );
  }
  return true;
}

function isObject(value: unknown): value is JsonObject {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
