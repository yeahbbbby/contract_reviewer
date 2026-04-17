import fs from 'node:fs/promises';
import path from 'node:path';
import * as Docx from 'docx';
import {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  PageNumber,
  Paragraph,
  Packer,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} from 'docx';

const chineseFont = 'FangSong';
const englishFont = 'Times New Roman';
const bodyFontSize = 24;
const titleFontSize = 28;
const { InsertedTextRun, DeletedTextRun } = Docx as any;

function splitRuns(text: string, bold = false) {
  const chunks = text.match(/[\u4e00-\u9fff]+|[^\u4e00-\u9fff]+/g) ?? [text];
  return chunks.map((chunk) => ({
    text: chunk,
    font: /[\u4e00-\u9fff]/.test(chunk) ? chineseFont : englishFont,
    bold,
  }));
}

function paragraphFromText(text: string, options?: { bold?: boolean; centered?: boolean; fontSize?: number }) {
  return new Paragraph({
    alignment: options?.centered ? AlignmentType.CENTER : AlignmentType.LEFT,
    spacing: {
      before: 120,
      after: 120,
      line: 240,
      lineRule: 'auto',
    },
    children: splitRuns(text, options?.bold).map((item) => new TextRun({
      text: item.text,
      bold: item.bold,
      font: item.font,
      size: options?.fontSize ?? bodyFontSize,
    })),
  });
}

function isTableSeparatorLine(line: string) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function parseTableBlock(lines: string[]) {
  if (lines.length < 2 || !isTableSeparatorLine(lines[1])) {
    return null;
  }

  const parseRow = (line: string) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
  const header = parseRow(lines[0]);
  const rows = lines.slice(2).map(parseRow).filter((row) => row.some((cell) => cell.length > 0));

  const tableRows = [header, ...rows].map((cells) => new TableRow({
    children: cells.map((cell) => new TableCell({
      width: { size: 100 / Math.max(header.length, 1), type: WidthType.PERCENTAGE },
      children: [paragraphFromText(cell)],
    })),
  }));

  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 1, color: '000000' },
      bottom: { style: BorderStyle.SINGLE, size: 1, color: '000000' },
      left: { style: BorderStyle.SINGLE, size: 1, color: '000000' },
      right: { style: BorderStyle.SINGLE, size: 1, color: '000000' },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 1, color: '000000' },
      insideVertical: { style: BorderStyle.SINGLE, size: 1, color: '000000' },
    },
    rows: tableRows,
  });
}

function parseMarkdownBlocks(markdown: string) {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const blocks: Array<Paragraph | Table> = [];
  let buffer: string[] = [];

  const flushParagraph = () => {
    const content = buffer.join(' ').trim();
    buffer = [];
    if (content) {
      blocks.push(paragraphFromText(content));
    }
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trimEnd();
    const trimmed = line.trim();

    if (!trimmed) {
      flushParagraph();
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,3})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      blocks.push(paragraphFromText(headingMatch[2], { bold: true, centered: headingMatch[1].length === 1, fontSize: headingMatch[1].length === 1 ? 28 : 24 }));
      continue;
    }

    const tableCandidate = [trimmed];
    let lookahead = index + 1;
    while (lookahead < lines.length) {
      const nextLine = lines[lookahead].trim();
      if (!nextLine) {
        break;
      }
      if (!nextLine.startsWith('|') && !/\|/.test(nextLine)) {
        break;
      }
      tableCandidate.push(nextLine);
      lookahead += 1;
      if (tableCandidate.length > 1 && isTableSeparatorLine(tableCandidate[1])) {
        continue;
      }
    }
    const table = parseTableBlock(tableCandidate);
    if (table) {
      flushParagraph();
      blocks.push(table);
      index += tableCandidate.length - 1;
      continue;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      flushParagraph();
      blocks.push(paragraphFromText(`• ${trimmed.replace(/^[-*]\s+/, '')}`));
      continue;
    }

    if (/^\d+[.)]\s+/.test(trimmed)) {
      flushParagraph();
      blocks.push(paragraphFromText(trimmed));
      continue;
    }

    buffer.push(trimmed);
  }

  flushParagraph();
  return blocks;
}

type RevisionOperation =
  | { kind: 'equal'; text: string }
  | { kind: 'insert'; text: string }
  | { kind: 'delete'; text: string };

function diffLines(originalLines: string[], revisedLines: string[]) {
  const originalCount = originalLines.length;
  const revisedCount = revisedLines.length;
  const dp = Array.from({ length: originalCount + 1 }, () => Array(revisedCount + 1).fill(0));

  for (let originalIndex = originalCount - 1; originalIndex >= 0; originalIndex -= 1) {
    for (let revisedIndex = revisedCount - 1; revisedIndex >= 0; revisedIndex -= 1) {
      if (originalLines[originalIndex] === revisedLines[revisedIndex]) {
        dp[originalIndex][revisedIndex] = dp[originalIndex + 1][revisedIndex + 1] + 1;
      } else {
        dp[originalIndex][revisedIndex] = Math.max(dp[originalIndex + 1][revisedIndex], dp[originalIndex][revisedIndex + 1]);
      }
    }
  }

  const operations: RevisionOperation[] = [];
  let originalIndex = 0;
  let revisedIndex = 0;

  while (originalIndex < originalCount && revisedIndex < revisedCount) {
    if (originalLines[originalIndex] === revisedLines[revisedIndex]) {
      operations.push({ kind: 'equal', text: originalLines[originalIndex] });
      originalIndex += 1;
      revisedIndex += 1;
      continue;
    }

    if (dp[originalIndex + 1][revisedIndex] >= dp[originalIndex][revisedIndex + 1]) {
      operations.push({ kind: 'delete', text: originalLines[originalIndex] });
      originalIndex += 1;
    } else {
      operations.push({ kind: 'insert', text: revisedLines[revisedIndex] });
      revisedIndex += 1;
    }
  }

  while (originalIndex < originalCount) {
    operations.push({ kind: 'delete', text: originalLines[originalIndex] });
    originalIndex += 1;
  }

  while (revisedIndex < revisedCount) {
    operations.push({ kind: 'insert', text: revisedLines[revisedIndex] });
    revisedIndex += 1;
  }

  return operations;
}

function buildRevisionParagraph(text: string, kind: 'insert' | 'delete', revisionId: number) {
  const date = new Date().toISOString();
  const revisionRun = kind === 'insert'
    ? new InsertedTextRun({ id: revisionId, author: 'Copilot', date, text })
    : new DeletedTextRun({ id: revisionId, author: 'Copilot', date, text });

  return new Paragraph({
    alignment: AlignmentType.LEFT,
    spacing: {
      before: 120,
      after: 120,
      line: 240,
      lineRule: 'auto',
    },
    children: [revisionRun as never],
  });
}

export async function writeDocxFile(input: {
  filePath: string;
  title: string;
  bodyMarkdown: string;
}) {
  const escapedTitle = input.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const bodyWithoutDuplicateTitle = input.bodyMarkdown
    .replace(new RegExp(`^\\s*#{1,3}\\s*${escapedTitle}\\s*(?:\\r?\\n)?`), '')
    .replace(new RegExp(`^\\s*${escapedTitle}\\s*(?:\\r?\\n)?`), '')
    .trimStart();

  const footer = new Footer({
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [
          new TextRun({ text: '第 ' }),
          new TextRun({ children: [PageNumber.CURRENT] }),
          new TextRun({ text: ' 页' }),
        ],
      }),
    ],
  });

  const document = new Document({
    sections: [
      {
        properties: {
          page: {
            margin: {
              top: 1440,
              right: 1440,
              bottom: 1440,
              left: 1440,
            },
          },
        },
        footers: { default: footer },
        children: [
          paragraphFromText(input.title, { bold: true, centered: true, fontSize: titleFontSize }),
          ...parseMarkdownBlocks(bodyWithoutDuplicateTitle),
        ],
      },
    ],
    styles: {
      default: {
        document: {
          run: {
            font: chineseFont,
            size: bodyFontSize,
          },
          paragraph: {
            spacing: {
              before: 120,
              after: 120,
              line: 240,
              lineRule: 'auto',
            },
          },
        },
      },
    },
  });

  await fs.mkdir(path.dirname(input.filePath), { recursive: true });
  const buffer = await Packer.toBuffer(document);
  await fs.writeFile(input.filePath, buffer);
}

export async function writeRedlineDocxFile(input: {
  filePath: string;
  title: string;
  originalBodyMarkdown: string;
  revisedBodyMarkdown: string;
}) {
  const escapedTitle = input.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const originalBody = input.originalBodyMarkdown
    .replace(new RegExp(`^\s*#{1,3}\s*${escapedTitle}\s*(?:\r?\n)?`), '')
    .replace(new RegExp(`^\s*${escapedTitle}\s*(?:\r?\n)?`), '')
    .trim();
  const revisedBody = input.revisedBodyMarkdown
    .replace(new RegExp(`^\s*#{1,3}\s*${escapedTitle}\s*(?:\r?\n)?`), '')
    .replace(new RegExp(`^\s*${escapedTitle}\s*(?:\r?\n)?`), '')
    .trim();

  const originalLines = originalBody.split(/\r?\n/).map((line) => line.trimEnd()).filter((line) => line.trim().length > 0);
  const revisedLines = revisedBody.split(/\r?\n/).map((line) => line.trimEnd()).filter((line) => line.trim().length > 0);
  const operations = diffLines(originalLines, revisedLines);

  const footer = new Footer({
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [
          new TextRun({ text: '第 ' }),
          new TextRun({ children: [PageNumber.CURRENT] }),
          new TextRun({ text: ' 页' }),
        ],
      }),
    ],
  });

  const document = new Document({
    sections: [
      {
        properties: {
          page: {
            margin: {
              top: 1440,
              right: 1440,
              bottom: 1440,
              left: 1440,
            },
          },
        },
        footers: { default: footer },
        children: [
          paragraphFromText(input.title, { bold: true, centered: true, fontSize: titleFontSize }),
          ...operations.map((operation, index) => {
            const revisionId = index + 1;
            if (operation.kind === 'equal') {
              return paragraphFromText(operation.text);
            }
            return buildRevisionParagraph(operation.text, operation.kind, revisionId);
          }),
        ],
      },
    ],
    styles: {
      default: {
        document: {
          run: {
            font: chineseFont,
            size: bodyFontSize,
          },
          paragraph: {
            spacing: {
              before: 120,
              after: 120,
              line: 240,
              lineRule: 'auto',
            },
          },
        },
      },
    },
  });

  await fs.mkdir(path.dirname(input.filePath), { recursive: true });
  const buffer = await Packer.toBuffer(document);
  await fs.writeFile(input.filePath, buffer);
}