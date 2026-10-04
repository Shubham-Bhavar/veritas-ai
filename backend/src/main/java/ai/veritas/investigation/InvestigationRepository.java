package ai.veritas.investigation;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

public interface InvestigationRepository extends JpaRepository<Investigation, UUID> {

    List<Investigation> findByOwnerIdOrderByUpdatedAtDesc(Long ownerId);

    Optional<Investigation> findByIdAndOwnerId(UUID id, Long ownerId);
}
