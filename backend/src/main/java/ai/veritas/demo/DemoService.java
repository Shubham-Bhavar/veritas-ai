package ai.veritas.demo;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import ai.veritas.common.ApiException;
import ai.veritas.config.AppProperties;
import ai.veritas.document.BytesMultipartFile;
import ai.veritas.document.DocumentService;
import ai.veritas.investigation.Investigation;
import ai.veritas.investigation.InvestigationService;

/**
 * Loads the bundled demo investigation. The documents are ordinary files sent through the
 * normal upload and indexing pipeline: nothing about the results is precomputed.
 */
@Service
public class DemoService {

    private static final Map<String, String> TYPES = Map.of("pdf", "application/pdf", "png", "image/png", "txt", "text/plain",
            "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document");

    private final InvestigationService investigations;
    private final DocumentService documents;
    private final AppProperties props;

    public DemoService(InvestigationService investigations, DocumentService documents, AppProperties props) {
        this.investigations = investigations;
        this.documents = documents;
        this.props = props;
    }

    public Investigation load(Long userId) {
        if (!props.demo().enabled()) {
            throw ApiException.notFound("Demo mode is disabled on this server.");
        }
        List<MultipartFile> files = new ArrayList<>();
        try {
            Resource[] resources = new PathMatchingResourcePatternResolver().getResources("classpath:demo/*.*");
            Arrays.sort(resources, Comparator.comparing(Resource::getFilename));
            for (Resource r : resources) {
                String name = r.getFilename();
                String ext = name.substring(name.lastIndexOf('.') + 1).toLowerCase();
                files.add(new BytesMultipartFile(name, TYPES.getOrDefault(ext, "application/octet-stream"),
                        r.getInputStream().readAllBytes()));
            }
        } catch (IOException e) {
            throw new IllegalStateException("Demo documents are missing from the build", e);
        }
        Investigation inv = investigations.create(userId, "NMS 2026 · Scholarship eligibility review",
                "Two applicants, two years of guidelines, a state rulebook and a government circular. "
                        + "Decide who is eligible, and prove it.", true);
        documents.upload(inv.getId(), files);
        return inv;
    }
}
