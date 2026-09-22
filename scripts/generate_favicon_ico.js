const fs = require('fs');
const path = require('path');

const source = path.resolve(__dirname, '../static/brand/png/favicon-512.png');
const target = path.resolve(__dirname, '../static/favicon.ico');
const png = fs.readFileSync(source);
const header = Buffer.alloc(22);

header.writeUInt16LE(0, 0);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(1, 4);
header.writeUInt8(0, 6);
header.writeUInt8(0, 7);
header.writeUInt8(0, 8);
header.writeUInt8(0, 9);
header.writeUInt16LE(1, 10);
header.writeUInt16LE(32, 12);
header.writeUInt32LE(png.length, 14);
header.writeUInt32LE(header.length, 18);

fs.writeFileSync(target, Buffer.concat([header, png]));
