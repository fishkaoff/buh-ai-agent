#!/usr/bin/env node
/**
 * Извлечение данных из $metadata 1С (XML) — портативный, без зависимостей.
 *
 * Использование:
 *   node metadata_extract.js <metadata.xml> enums                 — все перечисления и члены
 *   node metadata_extract.js <metadata.xml> enum <Имя>            — члены одного перечисления
 *   node metadata_extract.js <metadata.xml> find <подстрока>      — EntitySet по подстроке имени
 *   node metadata_extract.js <metadata.xml> fields <EntitySet> [--relations]
 *
 * EntitySet ищется по Name в EntityContainer; поля — по EntityType.
 */
const fs = require("fs");

const [file, cmd, arg, flag] = process.argv.slice(2);
if (!file || !cmd) {
  console.error("Использование: node metadata_extract.js <metadata.xml> enums|enum <Имя>|find <подстрока>|fields <EntitySet> [--relations]");
  process.exit(1);
}
const xml = fs.readFileSync(file, "utf8");

function enumMembers(name) {
  const re = new RegExp('<EnumType Name="' + name + '"[\\s\\S]*?>([\\s\\S]*?)</EnumType>');
  const m = xml.match(re);
  return m ? [...m[1].matchAll(/<Member Name="([^"]+)"/g)].map(x => x[1]) : null;
}

if (cmd === "enums") {
  for (const m of xml.matchAll(/<EnumType Name="([^"]+)"[^>]*>([\s\S]*?)<\/EnumType>/g)) {
    const members = [...m[2].matchAll(/<Member Name="([^"]+)"/g)].map(x => x[1]);
    console.log(m[1] + ": " + members.join(", "));
  }
} else if (cmd === "enum") {
  const members = enumMembers(arg);
  console.log(members ? arg + ": " + members.join(", ") : "ПЕРЕЧИСЛЕНИЕ НЕ НАЙДЕНО: " + arg);
} else if (cmd === "find") {
  const q = arg.toLowerCase();
  const found = [...xml.matchAll(/<EntitySet\s+Name="([^"]+)"\s+EntityType="([^"]+)"/g)]
    .filter(m => m[1].toLowerCase().includes(q))
    .map(m => m[1] + "  →  " + m[2]);
  console.log(found.length ? found.join("\n") : "НИЧЕГО НЕ НАЙДЕНО");
} else if (cmd === "fields") {
  // EntityType атрибут совпадает с именем EntitySet (напр. StandardODATA.Document_X_Товары)
  const es = xml.match(new RegExp('<EntitySet\\s+Name="' + arg + '"\\s+EntityType="([^"]+)"'));
  const typeName = es ? es[1].split(".").pop() : arg;
  const te = xml.match(new RegExp('<EntityType Name="' + typeName + '"[\\s\\S]*?>([\\s\\S]*?)</EntityType>'));
  if (!te) { console.log("ТИП НЕ НАЙДЕН: " + typeName); process.exit(2); }
  for (const p of te[1].matchAll(/<Property\s+Name="([^"]+)"\s+Type="([^"]+)"(?:\s+Nullable="false")?/g)) {
    console.log(p[1] + ": " + p[2] + (p[3] ? " NOT NULL" : ""));
  }
  if (flag === "--relations") {
    for (const n of te[1].matchAll(/<NavigationProperty Name="([^"]+)"/g)) console.log("→ " + n[1]);
  }
} else {
  console.error("Неизвестная команда:", cmd);
  process.exit(1);
}
