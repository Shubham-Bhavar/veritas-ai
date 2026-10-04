package ai.veritas.document;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class DocumentServiceTest {

    @Test
    void filenamesCannotEscapeOrInjectMarkup() {
        assertThat(DocumentService.sanitize("../../etc/passwd.txt")).isEqualTo("passwd.txt");
        assertThat(DocumentService.sanitize("C:\\Users\\me\\report.pdf")).isEqualTo("report.pdf");
        assertThat(DocumentService.sanitize("<script>x</script>.pdf")).isEqualTo("script.pdf");
        assertThat(DocumentService.sanitize("..")).isEqualTo("document");
        assertThat(DocumentService.sanitize(null)).isEqualTo("document");
    }

    @Test
    void signaturesMustMatchTheExtension() {
        assertThat(DocumentService.signatureMatches("pdf", "%PDF-1.7".getBytes())).isTrue();
        assertThat(DocumentService.signatureMatches("pdf", new byte[] {(byte) 0x89, 'P', 'N', 'G'})).isFalse();
        assertThat(DocumentService.signatureMatches("docx", new byte[] {'P', 'K', 3, 4})).isTrue();
        assertThat(DocumentService.signatureMatches("txt", new byte[] {'a', 0, 'b'})).isFalse();
        assertThat(DocumentService.signatureMatches("jpg", new byte[] {(byte) 0xFF, (byte) 0xD8, (byte) 0xFF, 0})).isTrue();
    }
}
