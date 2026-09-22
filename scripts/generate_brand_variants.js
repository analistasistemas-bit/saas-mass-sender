const fs = require('fs');
const path = require('path');

const brand = path.resolve(__dirname, '../static/brand');
const lockups = ['symbol', 'horizontal', 'stacked'];

for (const lockup of lockups) {
  const source = fs.readFileSync(path.join(brand, `mass-sender-cofre-${lockup}.svg`), 'utf8');
  const ice = source
    .replaceAll('#2BCAC2', '#EEF8F7')
    .replaceAll('#C5FF64', '#EEF8F7');
  const monochrome = source
    .replaceAll('#0B1112', '#FFFFFF')
    .replaceAll('#2BCAC2', '#0B1112')
    .replaceAll('#C5FF64', '#0B1112')
    .replaceAll('#EEF8F7', '#0B1112');

  fs.writeFileSync(path.join(brand, `mass-sender-cofre-${lockup}-ice.svg`), ice);
  fs.writeFileSync(path.join(brand, `mass-sender-cofre-${lockup}-mono.svg`), monochrome);
}
