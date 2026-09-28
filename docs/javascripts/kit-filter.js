// Filter the kit catalog by text and by Side / Area / Role chips built from its columns.
function setupKitFilter() {
  const host = document.querySelector('.kit-filter');
  if (!host || host.dataset.ready) return;
  let next = host.nextElementSibling;
  while (next && !next.querySelector('table')) next = next.nextElementSibling;
  const table = next?.querySelector('table');
  if (!table) return;
  host.dataset.ready = 'true';

  const headers = [...table.tHead.rows[0].cells].map((cell) => cell.textContent.trim());
  const rows = [...table.tBodies[0].rows];
  const cellValues = (row, column) =>
    row.cells[column].textContent.split(',').map((value) => value.trim()).filter(Boolean);
  const picked = new Map();

  const search = document.createElement('input');
  search.type = 'search';
  search.placeholder = 'Filter kits';
  search.setAttribute('aria-label', 'Filter kits');
  host.append(search);

  for (const name of ['Side', 'Area', 'Role']) {
    const column = headers.indexOf(name);
    if (column < 0) continue;
    const order = (host.dataset[name.toLowerCase()] ?? '').split(',');
    const values = [...new Set(rows.flatMap((row) => cellValues(row, column)))].sort(
      (a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99),
    );
    const group = document.createElement('div');
    group.className = 'kit-filter__group';
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', name);
    const label = document.createElement('span');
    label.textContent = name;
    group.append(label);
    for (const value of values) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.textContent = value;
      chip.setAttribute('aria-pressed', 'false');
      chip.addEventListener('click', () => {
        const on = picked.get(column) !== value;
        for (const other of group.querySelectorAll('button')) other.setAttribute('aria-pressed', 'false');
        chip.setAttribute('aria-pressed', String(on));
        if (on) picked.set(column, value);
        else picked.delete(column);
        apply();
      });
      group.append(chip);
    }
    host.append(group);
  }

  const count = document.createElement('p');
  count.className = 'kit-filter__count';
  count.setAttribute('aria-live', 'polite');
  host.append(count);

  function apply() {
    const words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const row of rows) {
      const text = row.textContent.toLowerCase();
      const visible =
        words.every((word) => text.includes(word)) &&
        [...picked].every(([column, value]) => cellValues(row, column).includes(value));
      row.hidden = !visible;
      if (visible) shown += 1;
    }
    count.textContent = `${shown} of ${rows.length} kits`;
  }

  search.addEventListener('input', apply);
  apply();
}

// Material's instant navigation swaps pages without a reload; document$ fires on each.
if (window.document$) window.document$.subscribe(setupKitFilter);
else document.addEventListener('DOMContentLoaded', setupKitFilter);
