#!/usr/bin/env node
/**
 * Вычисление кандидата в следующий номер договора 1С (правила — SKILL.md).
 *
 * Использование:
 *   node next_contract_number.js [Ref_Key контрагента]
 *
 * Правило: max(числовых Номер по всем договорам) + 1; для владельца —
 * дополнительно проверяется, есть ли у него уже этот номер. «б/н» и нечисловые
 * номера игнорируются. Ничего не записывает — только предлагает кандидата.
 */
// Поиск корня проекта (каталог с config/onec-config.json) вверх от скрипта:
const fs = require("fs");
const path = require("path");
function findProjectRoot() {
  let dir = __dirname;
  for (let i = 0; i < 8; i++) {
    if (fs.existsSync(path.join(dir, "config", "onec-config.json"))) return dir;
    const up = path.dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  throw new Error("Не найден config/onec-config.json от " + __dirname);
}
const { client, rows, parseError } = require(path.join(findProjectRoot(), "config", "onec", "odata-client.js"));

(async () => {
  const ownerRef = process.argv[2];
  const c = client();
  const r = await c.req("GET", c.BASE + "Catalog_ДоговорыКонтрагентов?$format=json&$top=500&$select=Ref_Key,Description,Номер,Дата,ВидДоговора,Owner_Key,DeletionMark,ДоговорЗакрыт");
  if (r.status !== 200) {
    const e = parseError(r.status, r.body);
    console.error("Ошибка чтения договоров:", r.status, e ? e.message : r.body.slice(0, 200));
    process.exit(2);
  }
  const dogs = rows(r.body);
  const nums = dogs.map(d => ({ raw: d.Номер, n: parseInt(d.Номер, 10) })).filter(x => Number.isInteger(x.n) && x.n > 0);
  const maxGlobal = nums.reduce((m, x) => Math.max(m, x.n), 0);
  const candidate = maxGlobal + 1;

  const result = { maxGlobal, candidate, takenBy: dogs.filter(d => parseInt(d.Номер, 10) === candidate).map(d => d.Description) };
  if (ownerRef) {
    const own = dogs.filter(d => d.Owner_Key === ownerRef);
    result.ownerContracts = own.map(d => ({ номер: d.Номер, описание: d.Description, вид: d.ВидДоговора, закрыт: d.ДоговорЗакрыт }));
  }
  console.log(JSON.stringify(result, null, 2));
  console.log(
    "\nРекомендация: Номер = " + result.candidate +
    (result.takenBy.length ? " (ЗАНЯТ: " + result.takenBy.join("; ") + " — выберите другой)" : " (свободен)") +
    "; Description = \"" + result.candidate + " от " + new Date().toLocaleDateString("ru-RU") + "\" либо \"б/н\" по согласованию с пользователем."
  );
})().catch(e => { console.error("FAIL:", e.message); process.exit(1); });
