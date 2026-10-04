package ai.veritas.ai;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.Map;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

import ai.veritas.common.ApiException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * Client for the internal evidence service. Translates its structured errors into API errors
 * and distinguishes "your input is wrong" (4xx) from "the AI service is down" (503).
 */
@Component
public class AiClient {

    private static final Logger log = LoggerFactory.getLogger(AiClient.class);

    private final RestClient ingest;
    private final RestClient query;
    private final ObjectMapper mapper;

    public AiClient(@Qualifier("aiIngestClient") RestClient ingest, @Qualifier("aiQueryClient") RestClient query,
            ObjectMapper mapper) {
        this.ingest = ingest;
        this.query = query;
        this.mapper = mapper;
    }

    /** Thrown for a document the service rejected (corrupt, unsupported, duplicate...). */
    public static class Rejected extends RuntimeException {
        private final String code;

        public Rejected(String code, String message) {
            super(message);
            this.code = code;
        }

        public String getCode() {
            return code;
        }
    }

    public JsonNode ingest(UUID collectionId, UUID documentId, String filename, Path file) {
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("document_id", documentId.toString());
        HttpHeaders partHeaders = new HttpHeaders();
        partHeaders.setContentDisposition(ContentDisposition.formData().name("file").filename(filename, StandardCharsets.UTF_8).build());
        partHeaders.setContentType(MediaType.APPLICATION_OCTET_STREAM);
        body.add("file", new HttpEntity<>(new FileSystemResource(file), partHeaders));
        return call(() -> ingest.post().uri("/v1/collections/{c}/documents", collectionId)
                .contentType(MediaType.MULTIPART_FORM_DATA).body(body).retrieve().body(JsonNode.class), true);
    }

    public void deleteDocument(UUID collectionId, UUID documentId) {
        try {
            query.delete().uri("/v1/collections/{c}/documents/{d}", collectionId, documentId).retrieve().toBodilessEntity();
        } catch (RestClientException e) {
            log.warn("Could not delete document {} from the evidence store: {}", documentId, e.getMessage());
        }
    }

    public void deleteCollection(UUID collectionId) {
        try {
            query.delete().uri("/v1/collections/{c}", collectionId).retrieve().toBodilessEntity();
        } catch (RestClientException e) {
            log.warn("Could not delete collection {} from the evidence store: {}", collectionId, e.getMessage());
        }
    }

    public JsonNode investigate(UUID collectionId, String question) {
        return call(() -> query.post().uri("/v1/collections/{c}/investigate", collectionId)
                .contentType(MediaType.APPLICATION_JSON).body(Map.of("question", question)).retrieve().body(JsonNode.class), false);
    }

    public JsonNode get(String path, Object... vars) {
        return call(() -> query.get().uri(path, vars).retrieve().body(JsonNode.class), false);
    }

    public JsonNode post(String path, Object body, Object... vars) {
        return call(() -> query.post().uri(path, vars).contentType(MediaType.APPLICATION_JSON).body(body)
                .retrieve().body(JsonNode.class), false);
    }

    public byte[] pageImage(UUID collectionId, UUID documentId, int page, String chunkId, String sentence, boolean flags) {
        return call(() -> query.get().uri(b -> {
            var u = b.path("/v1/collections/{c}/documents/{d}/pages/{p}");
            if (chunkId != null) {
                u.queryParam("chunk_id", chunkId);
            }
            if (sentence != null) {
                u.queryParam("sentence", sentence);
            }
            if (flags) {
                u.queryParam("flags", "true");
            }
            return u.build(collectionId, documentId, page);
        }).accept(MediaType.IMAGE_PNG).retrieve().body(byte[].class), false);
    }

    public JsonNode health() {
        return query.get().uri("/health").retrieve().body(JsonNode.class);
    }

    private interface Call<T> {
        T run();
    }

    private <T> T call(Call<T> c, boolean ingestion) {
        try {
            return c.run();
        } catch (RestClientResponseException e) {
            HttpStatusCode status = e.getStatusCode();
            String code = "AI_ERROR";
            String message = "The evidence service could not complete the request.";
            try {
                JsonNode body = mapper.readTree(e.getResponseBodyAsString());
                code = body.path("code").asString(code);
                message = body.path("message").asString(message);
            } catch (RuntimeException ignored) {
                // non-JSON error body
            }
            if (status.value() == 503 || status.is5xxServerError()) {
                log.error("Evidence service error {} {}: {}", status.value(), code, message);
                throw ApiException.unavailable("The evidence service is unavailable right now. Please try again shortly.");
            }
            if (status.value() == 401) {
                log.error("Evidence service rejected the internal token: check AI_INTERNAL_TOKEN on both services");
                throw ApiException.unavailable("The evidence service is misconfigured.");
            }
            if (ingestion) {
                throw new Rejected(code, message);
            }
            throw new ApiException(status.value() == 404 ? HttpStatus.NOT_FOUND : HttpStatus.BAD_REQUEST, code, message);
        } catch (RestClientException e) {
            log.error("Evidence service unreachable: {}", e.getMessage());
            throw ApiException.unavailable("The evidence service is unavailable right now. Please try again shortly.");
        }
    }
}
