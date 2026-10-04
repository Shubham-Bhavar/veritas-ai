package ai.veritas;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import ai.veritas.ai.AiClient;
import ai.veritas.common.ApiException;
import ai.veritas.document.DocumentRepository;
import ai.veritas.document.EvidenceDocument;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@SpringBootTest
@AutoConfigureMockMvc
class ApiIntegrationTest {

    @DynamicPropertySource
    static void props(DynamicPropertyRegistry r) throws Exception {
        r.add("spring.datasource.url", () -> "jdbc:h2:mem:veritas-test;MODE=PostgreSQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1");
        r.add("app.security.jwt-secret", () -> "test-secret-test-secret-test-secret-0123456789");
        Path dir = Files.createTempDirectory("veritas-uploads");
        r.add("app.storage.dir", dir::toString);
        r.add("management.server.port", () -> "0");
    }

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;
    @Autowired DocumentRepository documents;
    @Autowired ai.veritas.user.UserRepository users;
    @MockitoBean AiClient ai;

    @BeforeEach
    void aiDefaults() {
        when(ai.ingest(any(), any(), anyString(), any())).thenAnswer(inv -> json("""
                {"kind":"text","title":"Notes","role":"reference","doc_date":null,"pages":null,"chunks":3,"facts":1,
                 "ocr_used":false,"quality":1.0,"security_flags":0,"warnings":[],"timings":{"extract_ms":1,"embed_ms":2}}"""));
        when(ai.get(anyString(), any())).thenReturn(json("""
                {"documents":1,"chunks":3,"facts":1,"conflicts_unresolved":0,"conflicts_resolved":0}"""));
    }

    private JsonNode json(String s) {
        return mapper.readTree(s);
    }

    private String guestToken() throws Exception {
        String body = mvc.perform(post("/api/auth/guest")).andExpect(status().isCreated()).andReturn().getResponse().getContentAsString();
        return "Bearer " + mapper.readTree(body).path("token").asString();
    }

    private String createInvestigation(String token) throws Exception {
        String body = mvc.perform(post("/api/investigations").header("Authorization", token)
                        .contentType(MediaType.APPLICATION_JSON).content("{\"title\":\"Contract review\"}"))
                .andExpect(status().isCreated()).andReturn().getResponse().getContentAsString();
        return mapper.readTree(body).path("id").asString();
    }

    @Test
    void protectedEndpointsRequireAToken() throws Exception {
        mvc.perform(get("/api/investigations")).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/investigations").header("Authorization", "Bearer not-a-token")).andExpect(status().isUnauthorized());
    }

    @Test
    void aValidTokenForADeletedAccountIsRejectedCleanly() throws Exception {
        String token = guestToken();
        String body = mvc.perform(get("/api/auth/me").header("Authorization", token)).andReturn().getResponse().getContentAsString();
        users.deleteById(mapper.readTree(body).path("id").asLong());
        mvc.perform(get("/api/auth/me").header("Authorization", token)).andExpect(status().isUnauthorized());
        mvc.perform(post("/api/investigations").header("Authorization", token)
                        .contentType(MediaType.APPLICATION_JSON).content("{\"title\":\"x\"}"))
                .andExpect(status().isUnauthorized()); // not a confusing 409 from a foreign-key violation
    }

    @Test
    void investigationsArePrivateToTheirOwner() throws Exception {
        String alice = guestToken();
        String bob = guestToken();
        String id = createInvestigation(alice);
        mvc.perform(get("/api/investigations/" + id).header("Authorization", alice)).andExpect(status().isOk());
        // someone else's investigation is indistinguishable from one that does not exist
        mvc.perform(get("/api/investigations/" + id).header("Authorization", bob)).andExpect(status().isNotFound());
        mvc.perform(post("/api/investigations/" + id + "/questions").header("Authorization", bob)
                .contentType(MediaType.APPLICATION_JSON).content("{\"question\":\"What is the limit?\"}"))
                .andExpect(status().isNotFound());
    }

    @Test
    void uploadsAreValidatedPerFile() throws Exception {
        String token = guestToken();
        String id = createInvestigation(token);
        byte[] png = {(byte) 0x89, 'P', 'N', 'G', 13, 10, 26, 10, 0, 0};
        mvc.perform(multipart("/api/investigations/" + id + "/documents")
                        .file(new MockMultipartFile("files", "renamed.pdf", "application/pdf", png))
                        .file(new MockMultipartFile("files", "virus.exe", "application/octet-stream", new byte[] {'M', 'Z'}))
                        .file(new MockMultipartFile("files", "empty.txt", "text/plain", new byte[0]))
                        .file(new MockMultipartFile("files", "../../etc/notes.txt", "text/plain",
                                "The fee is Rs. 500 and must be paid by 1 May 2026.".getBytes(StandardCharsets.UTF_8)))
                        .header("Authorization", token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.results[0].code").value("TYPE_MISMATCH"))
                .andExpect(jsonPath("$.results[1].code").value("UNSUPPORTED_TYPE"))
                .andExpect(jsonPath("$.results[2].code").value("EMPTY_FILE"))
                .andExpect(jsonPath("$.results[3].accepted").value(true))
                .andExpect(jsonPath("$.results[3].filename").value("notes.txt")); // path stripped
        awaitStatus(UUID.fromString(id), EvidenceDocument.Status.INDEXED); // leave no background work behind
    }

    @Test
    void duplicatesAreRejectedAndValidFilesAreIndexed() throws Exception {
        String token = guestToken();
        String id = createInvestigation(token);
        byte[] text = "Clause 4: payment is due within 30 days of the invoice date.".getBytes(StandardCharsets.UTF_8);
        mvc.perform(multipart("/api/investigations/" + id + "/documents")
                        .file(new MockMultipartFile("files", "a.txt", "text/plain", text)).header("Authorization", token))
                .andExpect(jsonPath("$.results[0].accepted").value(true));
        mvc.perform(multipart("/api/investigations/" + id + "/documents")
                        .file(new MockMultipartFile("files", "copy-of-a.txt", "text/plain", text)).header("Authorization", token))
                .andExpect(jsonPath("$.results[0].code").value("DUPLICATE"));

        EvidenceDocument doc = awaitStatus(UUID.fromString(id), EvidenceDocument.Status.INDEXED);
        assertThat(doc.getChunks()).isEqualTo(3);
    }

    @Test
    void aServiceOutageMarksTheDocumentFailedNotStuck() throws Exception {
        when(ai.ingest(any(), any(), anyString(), any()))
                .thenThrow(ApiException.unavailable("The evidence service is unavailable right now."));
        String token = guestToken();
        String id = createInvestigation(token);
        mvc.perform(multipart("/api/investigations/" + id + "/documents")
                .file(new MockMultipartFile("files", "b.txt", "text/plain", "Some text that is long enough to index.".getBytes()))
                .header("Authorization", token));
        EvidenceDocument doc = awaitStatus(UUID.fromString(id), EvidenceDocument.Status.FAILED);
        assertThat(doc.getErrorCode()).isEqualTo("AI_UNAVAILABLE");
    }

    @Test
    void askingRequiresIndexedDocumentsAndAValidQuestion() throws Exception {
        String token = guestToken();
        String id = createInvestigation(token);
        mvc.perform(post("/api/investigations/" + id + "/questions").header("Authorization", token)
                        .contentType(MediaType.APPLICATION_JSON).content("{\"question\":\"x\"}"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("VALIDATION"));
        mvc.perform(post("/api/investigations/" + id + "/questions").header("Authorization", token)
                        .contentType(MediaType.APPLICATION_JSON).content("{\"question\":\"What is the payment term?\"}"))
                .andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("NO_DOCUMENTS"));
    }

    @Test
    void anAiOutageDuringAQuestionIsA503() throws Exception {
        String token = guestToken();
        String id = createInvestigation(token);
        mvc.perform(multipart("/api/investigations/" + id + "/documents")
                .file(new MockMultipartFile("files", "c.txt", "text/plain", "Payment is due within 30 days of delivery.".getBytes()))
                .header("Authorization", token));
        awaitStatus(UUID.fromString(id), EvidenceDocument.Status.INDEXED);
        // stub only once background ingestion has finished using the mock
        when(ai.investigate(any(), anyString())).thenThrow(ApiException.unavailable("The evidence service is unavailable right now."));
        mvc.perform(post("/api/investigations/" + id + "/questions").header("Authorization", token)
                        .contentType(MediaType.APPLICATION_JSON).content("{\"question\":\"What is the payment term?\"}"))
                .andExpect(status().isServiceUnavailable()).andExpect(jsonPath("$.code").value("AI_UNAVAILABLE"));
    }

    @Test
    void answersArePersistedWithTheirClaimsAndCitations() throws Exception {
        String token = guestToken();
        String id = createInvestigation(token);
        mvc.perform(multipart("/api/investigations/" + id + "/documents")
                .file(new MockMultipartFile("files", "d.txt", "text/plain", "Payment is due within 30 days of delivery.".getBytes()))
                .header("Authorization", token));
        EvidenceDocument doc = awaitStatus(UUID.fromString(id), EvidenceDocument.Status.INDEXED);
        when(ai.investigate(any(), anyString())).thenReturn(json("""
                {"question":"What is the payment term?","engine":"extractive",
                 "verdict":{"status":"SUPPORTED","headline":"30 days"},
                 "confidence":{"score":0.82,"level":"HIGH","signals":[],"explanation":["High confidence"]},
                 "claims":[{"id":"C1","text":"Payment is due within 30 days.","status":"SUPPORTED","evidence":["E1"],"kind":"value","source":"engine","conflict_ids":[],"reasoning":"Stated once."}],
                 "evidence":[{"id":"E1","chunk_id":"%s#c0","document_id":"%s","page":null,"section":"Notes","stance":"supports","quote":"Payment is due within 30 days of delivery."}],
                 "conflicts":[],"timeline":[{"step":"retrieve","detail":"1 passage","ms":5}]}"""
                .formatted(doc.getId(), doc.getId())));
        String body = mvc.perform(post("/api/investigations/" + id + "/questions").header("Authorization", token)
                        .contentType(MediaType.APPLICATION_JSON).content("{\"question\":\"What is the payment term?\"}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.verdict.headline").value("30 days"))
                .andReturn().getResponse().getContentAsString();
        String qid = mapper.readTree(body).path("question_id").asString();
        mvc.perform(get("/api/investigations/" + id + "/questions").header("Authorization", token))
                .andExpect(jsonPath("$[0].status").value("SUPPORTED"));
        mvc.perform(get("/api/investigations/" + id + "/questions/" + qid).header("Authorization", token))
                .andExpect(jsonPath("$.claims[0].evidence[0]").value("E1"));
        mvc.perform(get("/api/investigations/" + id + "/timeline").header("Authorization", token))
                .andExpect(jsonPath("$[?(@.type == 'question.answered')]").exists());
    }

    @Test
    void registrationAndLoginValidateCredentials() throws Exception {
        mvc.perform(post("/api/auth/register").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"Ana\",\"email\":\"ana@example.com\",\"password\":\"short\"}"))
                .andExpect(status().isBadRequest());
        mvc.perform(post("/api/auth/register").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"Ana\",\"email\":\"ana@example.com\",\"password\":\"long-enough-password\"}"))
                .andExpect(status().isCreated());
        mvc.perform(post("/api/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"ana@example.com\",\"password\":\"wrong-password-123\"}"))
                .andExpect(status().isUnauthorized());
        mvc.perform(post("/api/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"ANA@example.com\",\"password\":\"long-enough-password\"}"))
                .andExpect(status().isOk());
    }

    private EvidenceDocument awaitStatus(UUID investigationId, EvidenceDocument.Status wanted) throws InterruptedException {
        for (int i = 0; i < 100; i++) {
            var docs = documents.findByInvestigationIdOrderByCreatedAtAsc(investigationId);
            var match = docs.stream().filter(d -> d.getStatus() == wanted).findFirst();
            if (match.isPresent()) {
                return match.get();
            }
            Thread.sleep(50);
        }
        throw new AssertionError("Document never reached " + wanted);
    }
}
