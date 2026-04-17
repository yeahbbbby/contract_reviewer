"""
文档解析模块
支持Word、PDF文档的解析和章节切分
"""
import re
from typing import Dict, List, Optional
from docx import Document
import PyPDF2
import pdfplumber


class DocumentParser:
    """文档解析器"""

    def __init__(self):
        self.section_patterns = [
            r'^第[一二三四五六七八九十百]+条',  # 第X条
            r'^第\d+条',  # 第1条
            r'^[一二三四五六七八九十]+[、\.]',  # 一、
            r'^\([一二三四五六七八九十]+\)',  # （一）
            r'^\d+[、\.]',  # 1.
            r'^\(\d+\)',  # (1)
        ]

    def parse(self, file_path: str) -> Dict:
        """
        解析文档

        Args:
            file_path: 文档路径

        Returns:
            解析结果字典
        """
        if file_path.endswith('.docx') or file_path.endswith('.doc'):
            return self._parse_word(file_path)
        elif file_path.endswith('.pdf'):
            return self._parse_pdf(file_path)
        else:
            raise ValueError(f"不支持的文件格式: {file_path}")

    def _parse_word(self, file_path: str) -> Dict:
        """解析Word文档"""
        doc = Document(file_path)

        full_text = []
        paragraphs = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                full_text.append(text)
                paragraphs.append({
                    'text': text,
                    'style': para.style.name,
                    'level': self._detect_level(text)
                })

        sections = self._split_sections(paragraphs)

        return {
            'full_text': '\n'.join(full_text),
            'paragraphs': paragraphs,
            'sections': sections,
            'metadata': {
                'total_paragraphs': len(paragraphs),
                'total_sections': len(sections)
            }
        }

    def _parse_pdf(self, file_path: str) -> Dict:
        """解析PDF文档"""
        full_text = []

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text.append(text)

        text_content = '\n'.join(full_text)
        lines = [line.strip() for line in text_content.split('\n') if line.strip()]

        paragraphs = [
            {
                'text': line,
                'style': 'Normal',
                'level': self._detect_level(line)
            }
            for line in lines
        ]

        sections = self._split_sections(paragraphs)

        return {
            'full_text': text_content,
            'paragraphs': paragraphs,
            'sections': sections,
            'metadata': {
                'total_paragraphs': len(paragraphs),
                'total_sections': len(sections)
            }
        }

    def _detect_level(self, text: str) -> int:
        """检测文本层级"""
        for i, pattern in enumerate(self.section_patterns):
            if re.match(pattern, text):
                return i + 1
        return 0

    def _split_sections(self, paragraphs: List[Dict]) -> List[Dict]:
        """切分章节"""
        sections = []
        current_section = None

        for para in paragraphs:
            if para['level'] > 0:
                # 新章节开始
                if current_section:
                    sections.append(current_section)

                current_section = {
                    'title': para['text'],
                    'level': para['level'],
                    'content': [],
                    'subsections': []
                }
            elif current_section:
                # 添加到当前章节
                current_section['content'].append(para['text'])

        # 添加最后一个章节
        if current_section:
            sections.append(current_section)

        return sections
