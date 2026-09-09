"""Printable patient copies; rendering never changes dispensing or inventory."""
from io import BytesIO
from xml.sax.saxutils import escape
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def render_prescription(prescription):
    buffer = BytesIO()
    green = colors.HexColor('#116b55')
    ink = colors.HexColor('#273c36')
    body = ParagraphStyle('Body', fontName='Helvetica', fontSize=10, leading=15, textColor=ink)
    heading = ParagraphStyle('Heading', parent=body, fontName='Helvetica-Bold', fontSize=12, spaceBefore=16, spaceAfter=8, keepWithNext=True)
    white = ParagraphStyle('Column', parent=body, fontName='Helvetica-Bold', fontSize=9, textColor=colors.white)

    def text(value, style=body):
        return Paragraph(escape(str(value)).replace('\n', '<br/>'), style)

    patient = prescription.patient
    doctor = prescription.doctor
    reference = f'RX-{prescription.pk:04d}'
    issued = timezone.localtime(prescription.created_at).strftime('%d %b %Y, %H:%M %Z')
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=42, leftMargin=42,
        topMargin=110, bottomMargin=58, title=f'Prescription {reference}', author='PohanTech')

    def page(canvas, document):
        canvas.saveState()
        width, height = A4
        canvas.setFillColor(green)
        canvas.roundRect(42, height-75, 36, 36, 8, fill=1, stroke=0)
        canvas.setStrokeColor(colors.white)
        canvas.setLineWidth(3)
        canvas.line(51, height-57, 69, height-57)
        canvas.line(60, height-66, 60, height-48)
        canvas.setFont('Helvetica-Bold', 21)
        canvas.drawString(90, height-56, 'PohanTech')
        canvas.setFont('Helvetica', 9)
        canvas.drawString(91, height-72, 'CONNECTED CARE | PATIENT PRESCRIPTION')
        canvas.setFont('Helvetica-Bold', 11)
        canvas.drawRightString(width-42, height-52, reference)
        canvas.setStrokeColor(colors.HexColor('#dce7df'))
        canvas.setLineWidth(.6)
        canvas.line(42, height-91, width-42, height-91)
        canvas.line(42, 43, width-42, 43)
        canvas.setFillColor(ink)
        canvas.setFont('Helvetica', 8)
        canvas.drawString(42, 29, f'{reference} | Patient copy')
        canvas.drawRightString(width-42, 29, f'Page {document.page}')
        canvas.restoreState()

    story = [text(f'Issued: {issued}'), Spacer(1, 12)]
    details = Table([
        [text('PATIENT', heading), text('PRESCRIBING DOCTOR', heading)],
        [text(patient.name), text(doctor.name)],
        [text(f'Father: {patient.father_name}'), text(doctor.specialization)],
        [text(f'Patient reference: PT-{patient.pk:04d}'), text(f'Experience: {doctor.experience} years')],
        [text(f'Visit type: {patient.visit_type}'), text(f'Service: {patient.service.name}')],
    ], colWidths=[doc.width/2]*2)
    details.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'), ('LEFTPADDING',(0,0),(-1,-1),0),
        ('RIGHTPADDING',(0,0),(-1,-1),12), ('BOTTOMPADDING',(0,0),(-1,-1),5)]))
    story += [details, text('Diagnosis / sickness details', heading), text(prescription.diagnosis),
        text('Prescribed medicines', heading)]
    rows = [[text(h, white) for h in ['Medicine / type', 'Quantity', 'Dosage, frequency & duration']]]
    for item in prescription.items.all():
        rows.append([text(f'{item.drug.name}\n{item.drug.type}'), text(item.quantity), text(item.dosage)])
    medicines = Table(rows, colWidths=[doc.width*.38, doc.width*.13, doc.width*.49], repeatRows=1, splitInRow=1)
    medicines.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),green), ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),10), ('RIGHTPADDING',(0,0),(-1,-1),10),
        ('TOPPADDING',(0,0),(-1,-1),10), ('BOTTOMPADDING',(0,0),(-1,-1),10),
        ('LINEBELOW',(0,1),(-1,-1),.5,colors.HexColor('#e4ebe6'))]))
    story += [medicines, text('Patient instructions', heading), text(prescription.instructions),
        Spacer(1, 25), text('Doctor signature / stamp: __________________________________')]
    doc.build(story, onFirstPage=page, onLaterPages=page)
    buffer.seek(0)
    return buffer
